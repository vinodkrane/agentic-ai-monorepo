"""Lambda entry point for ingestion.

S3 (ObjectCreated) -> SQS -> this lambda.
For each file: download, parse, chunk, embed, index into OpenSearch, and
keep the status row in DynamoDB up to date so GET /documents/{doc_id} works.

We return batchItemFailures so only the failed messages go back to the
queue (and eventually the DLQ), not the whole batch.

Why lambda and not EC2/ECS workers: ingest is parse + Bedrock calls + bulk
index, it finishes well inside 15 min and doesn't need torch. If we add OCR
or layout models this should move to ECS Fargate workers polling the same
queue, see docs/architecture.md.
"""
import logging

from app import config, status
from app.aws import client
from app.embeddings import embed_many
from app.ingest import indexer
from app.ingest.chunker import make_chunks
from app.ingest.events import s3_objects_from_sqs
from app.ingest.parser import UnsupportedFile, parse

log = logging.getLogger()
log.setLevel(logging.INFO)

_index_checked = False


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


def process(item):
    """Handle one S3 object. Returns True if the SQS message should be retried."""
    key = item["key"]
    obj = client("s3").get_object(Bucket=item["bucket"], Key=key)
    meta = obj.get("Metadata", {})
    doc_id = meta.get("doc-id")

    if not doc_id:
        # everything should come through the API. something put a file
        # straight into the bucket, nothing to report status against
        log.error("no doc-id metadata on %s, skipping", key)
        return False

    if not status.start_processing(doc_id, item["receive_count"]):
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
        log.exception("failed to ingest %s (%s) attempt %d", doc_id, key, item["receive_count"])
        if item["receive_count"] >= config.MAX_RECEIVE_COUNT:
            # last try, the message goes to the DLQ after this
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


def lambda_handler(event, context):
    global _index_checked
    if not _index_checked:
        indexer.ensure_index()
        _index_checked = True

    failures = []
    for item in s3_objects_from_sqs(event):
        try:
            retry = process(item)
        except Exception:
            # e.g. s3 get_object or dynamodb down, nothing recorded yet
            log.exception("error handling %s", item["key"])
            retry = True
        if retry:
            failures.append({"itemIdentifier": item["message_id"]})

    return {"batchItemFailures": failures}
