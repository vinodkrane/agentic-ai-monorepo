"""Document ingest status, stored in DynamoDB (one item per doc_id).

    queued -> processing -> completed
                 |   ^
                 v   |  (redrive from DLQ)
               failed

    queued/processing -> skipped    (unsupported file, no text, no groups)
    completed         -> replaced   (a newer upload replaced this doc)

Every update is conditional so a duplicate or late SQS message can't move a
doc backwards, e.g. completed -> processing.
"""
import logging
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from app import config
from app.aws import table

log = logging.getLogger(__name__)

QUEUED = "queued"
PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"
SKIPPED = "skipped"
REPLACED = "replaced"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table():
    return table(config.STATUS_TABLE)


def _update(doc_id, new_status, allowed_from, extra=None):
    """Set status only if the current status is in allowed_from.
    Returns False if the condition failed (not an error, just a no-op)."""
    names = {"#s": "status"}
    values = {":new": new_status, ":now": _now()}
    sets = ["#s = :new", "updated_at = :now"]

    for key, value in (extra or {}).items():
        names[f"#{key}"] = key
        values[f":{key}"] = value
        sets.append(f"#{key} = :{key}")

    allowed_keys = []
    for i, s in enumerate(allowed_from):
        values[f":from{i}"] = s
        allowed_keys.append(f":from{i}")

    try:
        _table().update_item(
            Key={"doc_id": doc_id},
            UpdateExpression="SET " + ", ".join(sets),
            ConditionExpression=f"attribute_exists(doc_id) AND #s IN ({', '.join(allowed_keys)})",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            log.info("status %s -> %s not allowed for %s, skipping", allowed_from, new_status, doc_id)
            return False
        raise


def create(doc_id, filename, s3_key, groups, uploaded_by, replaces=None):
    item = {
        "doc_id": doc_id,
        "status": QUEUED,
        "filename": filename,
        "s3_key": s3_key,
        "groups": groups,
        "uploaded_by": uploaded_by,
        "created_at": _now(),
        "updated_at": _now(),
    }
    if replaces:
        item["replaces"] = replaces
    _table().put_item(Item=item, ConditionExpression="attribute_not_exists(doc_id)")
    return item


def get(doc_id):
    return _table().get_item(Key={"doc_id": doc_id}).get("Item")


def start_processing(doc_id, attempt):
    # failed is allowed here so a DLQ redrive can pick the doc up again
    return _update(doc_id, PROCESSING, [QUEUED, PROCESSING, FAILED], {"attempts": attempt, "error": ""})


def mark_completed(doc_id, chunk_count):
    return _update(doc_id, COMPLETED, [PROCESSING], {"chunk_count": chunk_count})


def mark_failed(doc_id, error):
    return _update(doc_id, FAILED, [QUEUED, PROCESSING], {"error": error[:500]})


def mark_skipped(doc_id, reason):
    return _update(doc_id, SKIPPED, [QUEUED, PROCESSING], {"error": reason})


def mark_replaced(doc_id, by_doc_id):
    return _update(doc_id, REPLACED, [COMPLETED, FAILED, SKIPPED], {"replaced_by": by_doc_id})


def find_stuck(older_than_minutes=config.STUCK_AFTER_MINUTES):
    """Docs sitting in processing for too long. A scan is fine at our size,
    add a GSI on status if the table gets big."""
    cutoff = datetime.now(timezone.utc).timestamp() - older_than_minutes * 60
    stuck = []
    kwargs = {
        "FilterExpression": "#s = :p",
        "ExpressionAttributeNames": {"#s": "status"},
        "ExpressionAttributeValues": {":p": PROCESSING},
    }
    while True:
        resp = _table().scan(**kwargs)
        for item in resp.get("Items", []):
            if datetime.fromisoformat(item["updated_at"]).timestamp() < cutoff:
                stuck.append(item)
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return stuck
