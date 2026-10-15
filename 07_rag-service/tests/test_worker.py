"""Ingest worker against moto S3 + SQS + DynamoDB. Embeddings and
OpenSearch are stubbed."""
import json
import threading
import time

import pytest

from app import config, status
from app.aws import client
from app.ingest import worker


@pytest.fixture
def stubbed(aws, monkeypatch):
    calls = {"deleted": [], "indexed": 0}

    monkeypatch.setattr(worker, "embed_many", lambda texts: [[0.0] * 4 for _ in texts])
    monkeypatch.setattr(worker.indexer, "delete_doc", lambda doc_id: calls["deleted"].append(doc_id))

    def fake_index(chunks, vectors):
        calls["indexed"] += len(chunks)
        return len(chunks)

    monkeypatch.setattr(worker.indexer, "index_chunks", fake_index)
    # failed messages come straight back so we don't have to wait in tests
    monkeypatch.setattr(config, "RETRY_DELAY_SECONDS", 0)
    return calls


@pytest.fixture
def sqs(aws):
    return client("sqs")


def upload(s3, sqs, doc_id, body=b"Full time staff get 25 days annual leave per year.", groups="all-staff",
           name="leave.md", replaces=""):
    """What the API + S3 notification would do."""
    key = f"uploads/{doc_id}/{name}"
    status.create(doc_id, name, key, [g for g in groups.split(",") if g], "bob", replaces=replaces or None)
    s3.put_object(Bucket=config.DOCS_BUCKET, Key=key, Body=body,
                  Metadata={"doc-id": doc_id, "groups": groups, "original-name": name, "replaces": replaces})
    send_event(sqs, key)
    return key


def send_event(sqs, key):
    body = {"Records": [{
        "eventName": "ObjectCreated:Put",
        "s3": {"bucket": {"name": config.DOCS_BUCKET}, "object": {"key": key}},
    }]}
    sqs.send_message(QueueUrl=config.INGEST_QUEUE_URL, MessageBody=json.dumps(body))


def queue_size(sqs):
    attrs = sqs.get_queue_attributes(
        QueueUrl=config.INGEST_QUEUE_URL,
        AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"],
    )["Attributes"]
    return int(attrs["ApproximateNumberOfMessages"]) + int(attrs["ApproximateNumberOfMessagesNotVisible"])


def test_completes_and_deletes_message(aws, sqs, stubbed):
    upload(aws, sqs, "d1")
    assert worker.poll_once(sqs, wait_seconds=0) == 1

    doc = status.get("d1")
    assert doc["status"] == "completed"
    assert doc["chunk_count"] == 1
    assert queue_size(sqs) == 0


def test_empty_queue(aws, sqs, stubbed):
    assert worker.poll_once(sqs, wait_seconds=0) == 0


def test_no_groups_is_skipped_and_deleted(aws, sqs, stubbed):
    upload(aws, sqs, "d1", groups="")
    worker.poll_once(sqs, wait_seconds=0)

    assert status.get("d1")["status"] == "skipped"
    assert stubbed["indexed"] == 0
    assert queue_size(sqs) == 0


def test_empty_text_is_skipped(aws, sqs, stubbed):
    upload(aws, sqs, "d1", body=b"   ")
    worker.poll_once(sqs, wait_seconds=0)
    assert "no text" in status.get("d1")["error"]


def test_error_is_retried_and_failed_on_last_attempt(aws, sqs, stubbed, monkeypatch):
    def boom(texts):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(worker, "embed_many", boom)
    upload(aws, sqs, "d1")

    for attempt in range(1, config.MAX_RECEIVE_COUNT):
        worker.poll_once(sqs, wait_seconds=0)
        doc = status.get("d1")
        assert doc["status"] == "processing", f"attempt {attempt}"
        assert queue_size(sqs) == 1  # message kept for retry

    worker.poll_once(sqs, wait_seconds=0)
    doc = status.get("d1")
    assert doc["status"] == "failed"
    assert "bedrock down" in doc["error"]
    assert doc["attempts"] == config.MAX_RECEIVE_COUNT


def test_recovers_on_retry(aws, sqs, stubbed, monkeypatch):
    real = worker.embed_many
    calls = {"n": 0}

    def flaky(texts):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("ThrottlingException")
        return real(texts)

    monkeypatch.setattr(worker, "embed_many", flaky)
    upload(aws, sqs, "d1")
    worker.poll_once(sqs, wait_seconds=0)
    worker.poll_once(sqs, wait_seconds=0)

    assert status.get("d1")["status"] == "completed"
    assert queue_size(sqs) == 0


def test_duplicate_delivery_is_dropped(aws, sqs, stubbed):
    key = upload(aws, sqs, "d1")
    send_event(sqs, key)  # SQS is at least once
    worker.poll_once(sqs, wait_seconds=0)
    worker.poll_once(sqs, wait_seconds=0)

    assert stubbed["indexed"] == 1
    assert queue_size(sqs) == 0


def test_replace_removes_old_chunks(aws, sqs, stubbed):
    upload(aws, sqs, "old")
    worker.poll_once(sqs, wait_seconds=0)

    upload(aws, sqs, "new", replaces="old")
    worker.poll_once(sqs, wait_seconds=0)

    assert status.get("new")["status"] == "completed"
    assert status.get("old")["status"] == "replaced"
    assert "old" in stubbed["deleted"]


def test_object_without_doc_id_is_dropped(aws, sqs, stubbed):
    aws.put_object(Bucket=config.DOCS_BUCKET, Key="uploads/x/manual.md", Body=b"dropped in by hand")
    send_event(sqs, "uploads/x/manual.md")
    worker.poll_once(sqs, wait_seconds=0)

    assert stubbed["indexed"] == 0
    assert queue_size(sqs) == 0


def test_heartbeat_extends_visibility(monkeypatch):
    monkeypatch.setattr(config, "HEARTBEAT_SECONDS", 0.05)

    class FakeSqs:
        def __init__(self):
            self.extended = 0
            self.lock = threading.Lock()

        def change_message_visibility(self, **kwargs):
            with self.lock:
                self.extended += 1

    fake = FakeSqs()
    with worker.keep_invisible(fake, "rh"):
        time.sleep(0.3)  # pretend we're embedding a big pdf
    seen = fake.extended
    time.sleep(0.15)

    assert seen >= 3
    assert fake.extended == seen  # heartbeat stops when the work is done


def test_stop_flag_ends_main_loop(aws, stubbed, monkeypatch):
    monkeypatch.setattr(worker.indexer, "ensure_index", lambda: None)
    monkeypatch.setattr(config, "POLL_WAIT_SECONDS", 0)

    def poll_then_stop(sqs, wait_seconds=0):
        worker._stop.set()
        return 0

    monkeypatch.setattr(worker, "poll_once", poll_then_stop)
    worker._stop.clear()
    worker.main()  # returns instead of looping forever
    worker._stop.clear()
