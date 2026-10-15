import json
from urllib.parse import unquote_plus


def s3_objects_from_message(body):
    """Pull (bucket, key) pairs out of one SQS message body carrying an S3 notification.

    Things that caught us out:
    - S3 sends an "s3:TestEvent" when the notification is first configured,
      it has no Records and must be skipped not failed.
    - keys are url encoded, spaces arrive as '+'.
    """
    data = json.loads(body)

    # if the queue is ever fed through SNS the real event is wrapped in "Message"
    if "Message" in data and isinstance(data["Message"], str):
        data = json.loads(data["Message"])

    if data.get("Event") == "s3:TestEvent":
        return []

    out = []
    for rec in data.get("Records", []):
        if not rec.get("eventName", "").startswith("ObjectCreated"):
            continue
        out.append((rec["s3"]["bucket"]["name"], unquote_plus(rec["s3"]["object"]["key"])))
    return out
