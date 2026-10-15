"""Ingest worker. Runs on the EC2 worker fleet (one container per instance).

S3 (ObjectCreated) -> SQS -> this worker -> OpenSearch, with the DynamoDB
status row updated along the way so GET /documents/{doc_id} works.

Loop:
  - long poll SQS for one message
  - keep the message invisible while we work on it (heartbeat thread)
  - parse, chunk, embed, index
  - success / skipped -> delete the message
  - error -> leave it, with a short backoff, SQS retries it. After
    MAX_RECEIVE_COUNT tries the redrive policy moves it to the DLQ

If the instance is killed mid document (scale-in, spot, crash) the message
just becomes visible again and another worker redoes it. Ingest is
idempotent: chunks for the doc_id are deleted before indexing and the status
updates are conditional.

    python -m app.ingest.worker
"""
import logging
import signal
import threading
from contextlib import contextmanager

from app import config, status
from app.aws import client
from app.embeddings import embed_many
from app.ingest import indexer
from app.ingest.chunker import make_chunks
from app.ingest.events import s3_objects_from_message
from app.ingest.parser import UnsupportedFile, parse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
log = logging.getLogger("worker")

_stop = threading.Event()


class SkipDoc(Exception):
    """Retrying won't help (no groups, no text...). Mark skipped, don't retry."""


def ingest_object(doc_id, obj):
    data = obj["Body"].read()
    meta = obj.get("Metadata", {})

    groups = [g for g in meta.get("groups", "").split(",") if g]
    if not groups:
        # no groups = nobody should see it. Don't guess.
        raise SkipDoc("no groups on the object")

    filename = meta.get("original-name") or "unknown"
    try:
        pages = parse(filename, data)
    except UnsupportedFile as e:
        raise SkipDoc(f"unsupported file type {e}")
    if not pages:
        raise SkipDoc("no text extracted (scanned pdf?)")

    chunks = make_chunks(doc_id, filename, pages, groups)
    vectors = embed_many([c["text"] for c in chunks])

    # a retry after a half finished run leaves partial chunks, clear them first
    indexer.delete_doc(doc_id)
    return indexer.index_chunks(chunks, vectors)


def process_object(bucket, key, receive_count):
    """Handle one S3 object. Returns True if the SQS message should be retried."""
    obj = client("s3").get_object(Bucket=bucket, Key=key)
    meta = obj.get("Metadata", {})
    doc_id = meta.get("doc-id")

    if not doc_id:
        # everything should come through the API. something put a file
        # straight into the bucket, nothing to report status against
        log.error("no doc-id metadata on %s, skipping", key)
        return False

    if not status.start_processing(doc_id, receive_count):
        # already completed/skipped/replaced - duplicate delivery from SQS
        log.info("doc %s not in a processable state, dropping message", doc_id)
        return False

    try:
        count = ingest_object(doc_id, obj)
    except SkipDoc as e:
        log.warning("skipping %s (%s): %s", doc_id, key, e)
        status.mark_skipped(doc_id, str(e))
        return False
    except Exception as e:
        log.exception("failed to ingest %s (%s) attempt %d", doc_id, key, receive_count)
        if receive_count >= config.MAX_RECEIVE_COUNT:
            # last try, SQS moves the message to the DLQ after this
            status.mark_failed(doc_id, f"{type(e).__name__}: {e}")
        return True

    status.mark_completed(doc_id, count)
    log.info("indexed %s doc_id=%s chunks=%d", key, doc_id, count)

    replaces = meta.get("replaces")
    if replaces:
        indexer.delete_doc(replaces)
        status.mark_replaced(replaces, doc_id)
        log.info("doc %s replaced %s", doc_id, replaces)
    return False


@contextmanager
def keep_invisible(sqs, receipt_handle):
    """Extend the message's visibility timeout every HEARTBEAT_SECONDS while
    we're working on it, so a big PDF doesn't get picked up by a second worker
    halfway through."""
    done = threading.Event()

    def beat():
        while not done.wait(config.HEARTBEAT_SECONDS):
            try:
                sqs.change_message_visibility(
                    QueueUrl=config.INGEST_QUEUE_URL,
                    ReceiptHandle=receipt_handle,
                    VisibilityTimeout=config.VISIBILITY_TIMEOUT,
                )
            except Exception:
                log.warning("visibility heartbeat failed", exc_info=True)

    t = threading.Thread(target=beat, daemon=True)
    t.start()
    try:
        yield
    finally:
        done.set()
        t.join()


def handle_message(sqs, msg):
    receive_count = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", 1))
    retry = False

    with keep_invisible(sqs, msg["ReceiptHandle"]):
        for bucket, key in s3_objects_from_message(msg["Body"]):
            try:
                retry = process_object(bucket, key, receive_count) or retry
            except Exception:
                # e.g. s3 get_object or dynamodb down, nothing recorded yet
                log.exception("error handling %s", key)
                retry = True

    if retry:
        # back off a bit more each time instead of waiting for the full timeout
        sqs.change_message_visibility(
            QueueUrl=config.INGEST_QUEUE_URL,
            ReceiptHandle=msg["ReceiptHandle"],
            VisibilityTimeout=config.RETRY_DELAY_SECONDS * receive_count,
        )
    else:
        sqs.delete_message(QueueUrl=config.INGEST_QUEUE_URL, ReceiptHandle=msg["ReceiptHandle"])
    return not retry


def poll_once(sqs, wait_seconds=config.POLL_WAIT_SECONDS):
    """Receive and handle at most one message. Returns how many were handled."""
    resp = sqs.receive_message(
        QueueUrl=config.INGEST_QUEUE_URL,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=wait_seconds,
        VisibilityTimeout=config.VISIBILITY_TIMEOUT,
        AttributeNames=["ApproximateReceiveCount"],
    )
    msgs = resp.get("Messages", [])
    for msg in msgs:
        handle_message(sqs, msg)
    return len(msgs)


def _on_signal(signum, frame):
    # docker stop / instance shutdown. finish the current doc, then exit
    log.info("got signal %s, stopping after the current message", signum)
    _stop.set()


def main():
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    if not config.INGEST_QUEUE_URL:
        raise SystemExit("INGEST_QUEUE_URL is not set")

    indexer.ensure_index()
    sqs = client("sqs")
    log.info("worker started, polling %s", config.INGEST_QUEUE_URL)

    while not _stop.is_set():
        try:
            poll_once(sqs)
        except Exception:
            # sqs hiccup, don't let the container die over it
            log.exception("poll failed, retrying in 5s")
            _stop.wait(5)

    log.info("worker stopped")


if __name__ == "__main__":
    main()
