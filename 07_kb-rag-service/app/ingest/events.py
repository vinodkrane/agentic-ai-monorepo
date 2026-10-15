import json
from urllib.parse import unquote_plus


def s3_objects_from_sqs(event):
    """Pull the S3 objects out of an SQS batch that carries S3 notifications.

    Returns a list of dicts: message_id, bucket, key, receive_count.

    Things that caught us out:
    - S3 sends an "s3:TestEvent" when the notification is first configured,
      it has no Records and must be skipped not failed.
    - keys are url encoded, spaces arrive as '+'.
    """
    out = []
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        # how many times SQS has handed out this message, 1 on the first try
        receive_count = int(record.get("attributes", {}).get("ApproximateReceiveCount", 1))

        # if the queue is fed through SNS the real event is wrapped in "Message"
        if "Message" in body and isinstance(body["Message"], str):
            body = json.loads(body["Message"])

        if body.get("Event") == "s3:TestEvent":
            continue

        for s3_rec in body.get("Records", []):
            if not s3_rec.get("eventName", "").startswith("ObjectCreated"):
                continue
            out.append({
                "message_id": record["messageId"],
                "bucket": s3_rec["s3"]["bucket"]["name"],
                "key": unquote_plus(s3_rec["s3"]["object"]["key"]),
                "receive_count": receive_count,
            })
    return out
