import json

from app.ingest.events import s3_objects_from_message


def _put(key):
    return {"Records": [{
        "eventName": "ObjectCreated:Put",
        "s3": {"bucket": {"name": "b"}, "object": {"key": key}},
    }]}


def test_parses_s3_put():
    assert s3_objects_from_message(json.dumps(_put("uploads/abc/my+file.pdf"))) == [("b", "uploads/abc/my file.pdf")]


def test_skips_test_event():
    body = {"Service": "Amazon S3", "Event": "s3:TestEvent", "Bucket": "b"}
    assert s3_objects_from_message(json.dumps(body)) == []


def test_ignores_deletes():
    body = {"Records": [{
        "eventName": "ObjectRemoved:Delete",
        "s3": {"bucket": {"name": "b"}, "object": {"key": "x.pdf"}},
    }]}
    assert s3_objects_from_message(json.dumps(body)) == []


def test_unwraps_sns_envelope():
    body = {"Type": "Notification", "Message": json.dumps(_put("a.txt"))}
    assert s3_objects_from_message(json.dumps(body)) == [("b", "a.txt")]
