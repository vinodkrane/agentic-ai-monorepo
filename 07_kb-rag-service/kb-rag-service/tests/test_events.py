import json

from app.ingest.events import s3_objects_from_sqs


def _sqs(body, msg_id="m1", receive_count=None):
    record = {"messageId": msg_id, "body": json.dumps(body)}
    if receive_count:
        record["attributes"] = {"ApproximateReceiveCount": str(receive_count)}
    return {"Records": [record]}


def _put(key):
    return {"Records": [{
        "eventName": "ObjectCreated:Put",
        "s3": {"bucket": {"name": "b"}, "object": {"key": key}},
    }]}


def test_parses_s3_put():
    out = s3_objects_from_sqs(_sqs(_put("uploads/abc/my+file.pdf")))
    assert out == [{"message_id": "m1", "bucket": "b", "key": "uploads/abc/my file.pdf", "receive_count": 1}]


def test_reads_receive_count():
    out = s3_objects_from_sqs(_sqs(_put("a.txt"), receive_count=3))
    assert out[0]["receive_count"] == 3


def test_skips_test_event():
    body = {"Service": "Amazon S3", "Event": "s3:TestEvent", "Bucket": "b"}
    assert s3_objects_from_sqs(_sqs(body)) == []


def test_ignores_deletes():
    body = {"Records": [{
        "eventName": "ObjectRemoved:Delete",
        "s3": {"bucket": {"name": "b"}, "object": {"key": "x.pdf"}},
    }]}
    assert s3_objects_from_sqs(_sqs(body)) == []


def test_unwraps_sns_envelope():
    body = {"Type": "Notification", "Message": json.dumps(_put("a.txt"))}
    assert s3_objects_from_sqs(_sqs(body))[0]["key"] == "a.txt"
