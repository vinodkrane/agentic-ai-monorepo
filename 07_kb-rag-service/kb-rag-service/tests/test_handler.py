"""Ingest handler with S3 + DynamoDB faked by moto, embeddings and
OpenSearch stubbed out."""
import json

import pytest

from app import config, status
from app.ingest import handler


@pytest.fixture
def stubbed(aws, monkeypatch):
    calls = {"deleted": [], "indexed": 0}

    monkeypatch.setattr(handler, "_index_checked", True)
    monkeypatch.setattr(handler, "embed_many", lambda texts: [[0.0] * 4 for _ in texts])
    monkeypatch.setattr(handler.indexer, "delete_doc", lambda doc_id: calls["deleted"].append(doc_id))

    def fake_index(chunks, vectors):
        calls["indexed"] += len(chunks)
        return len(chunks)

    monkeypatch.setattr(handler.indexer, "index_chunks", fake_index)
    return calls


def upload(s3, doc_id, body=b"Full time staff get 25 days annual leave per year.", groups="all-staff",
           name="leave.md", replaces=""):
    key = f"uploads/{doc_id}/{name}"
    status.create(doc_id, name, key, [g for g in groups.split(",") if g], "bob", replaces=replaces or None)
    s3.put_object(Bucket=config.DOCS_BUCKET, Key=key, Body=body,
                  Metadata={"doc-id": doc_id, "groups": groups, "original-name": name, "replaces": replaces})
    return key


def event(key, receive_count=1, msg_id="m1"):
    body = {"Records": [{
        "eventName": "ObjectCreated:Put",
        "s3": {"bucket": {"name": config.DOCS_BUCKET}, "object": {"key": key}},
    }]}
    return {"Records": [{
        "messageId": msg_id,
        "body": json.dumps(body),
        "attributes": {"ApproximateReceiveCount": str(receive_count)},
    }]}


def test_completes(aws, stubbed):
    key = upload(aws, "d1")
    out = handler.lambda_handler(event(key), None)

    assert out == {"batchItemFailures": []}
    doc = status.get("d1")
    assert doc["status"] == "completed"
    assert doc["chunk_count"] == 1


def test_no_groups_is_skipped_not_retried(aws, stubbed):
    key = upload(aws, "d1", groups="")
    out = handler.lambda_handler(event(key), None)

    assert out["batchItemFailures"] == []
    assert status.get("d1")["status"] == "skipped"
    assert stubbed["indexed"] == 0


def test_empty_text_is_skipped(aws, stubbed):
    key = upload(aws, "d1", body=b"   ")
    handler.lambda_handler(event(key), None)
    assert "no text" in status.get("d1")["error"]


def test_error_retries_and_only_fails_on_last_attempt(aws, stubbed, monkeypatch):
    def boom(texts):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(handler, "embed_many", boom)
    key = upload(aws, "d1")

    out = handler.lambda_handler(event(key, receive_count=1), None)
    assert out["batchItemFailures"] == [{"itemIdentifier": "m1"}]
    assert status.get("d1")["status"] == "processing"

    out = handler.lambda_handler(event(key, receive_count=config.MAX_RECEIVE_COUNT), None)
    assert out["batchItemFailures"] == [{"itemIdentifier": "m1"}]
    doc = status.get("d1")
    assert doc["status"] == "failed"
    assert "bedrock down" in doc["error"]


def test_duplicate_delivery_is_dropped(aws, stubbed):
    key = upload(aws, "d1")
    handler.lambda_handler(event(key), None)
    handler.lambda_handler(event(key, receive_count=2), None)
    assert stubbed["indexed"] == 1  # second message didn't re-index


def test_replace_removes_old_chunks(aws, stubbed):
    old_key = upload(aws, "old")
    handler.lambda_handler(event(old_key), None)

    new_key = upload(aws, "new", replaces="old")
    handler.lambda_handler(event(new_key), None)

    assert status.get("new")["status"] == "completed"
    assert status.get("old")["status"] == "replaced"
    assert "old" in stubbed["deleted"]


def test_object_without_doc_id_is_ignored(aws, stubbed):
    aws.put_object(Bucket=config.DOCS_BUCKET, Key="uploads/x/manual.md", Body=b"dropped in by hand")
    out = handler.lambda_handler(event("uploads/x/manual.md"), None)
    assert out["batchItemFailures"] == []
    assert stubbed["indexed"] == 0
