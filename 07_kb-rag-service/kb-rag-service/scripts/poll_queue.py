"""Local stand-in for the SQS -> Lambda trigger.

Long polls the localstack queue and calls the lambda handler with the same
event shape AWS would send. Ctrl+C to stop.
"""
import logging

from app import config
from app.aws import client
from app.ingest.handler import lambda_handler

logging.basicConfig(level=logging.INFO)


def main():
    sqs = client("sqs")
    print(f"polling {config.INGEST_QUEUE_URL}")
    while True:
        resp = sqs.receive_message(
            QueueUrl=config.INGEST_QUEUE_URL,
            MaxNumberOfMessages=5,
            WaitTimeSeconds=10,
            AttributeNames=["ApproximateReceiveCount"],
        )
        msgs = resp.get("Messages", [])
        if not msgs:
            continue

        event = {"Records": [
            {"messageId": m["MessageId"], "body": m["Body"], "attributes": m.get("Attributes", {})}
            for m in msgs
        ]}
        result = lambda_handler(event, None)
        failed = {f["itemIdentifier"] for f in result["batchItemFailures"]}

        for m in msgs:
            if m["MessageId"] not in failed:
                sqs.delete_message(QueueUrl=config.INGEST_QUEUE_URL, ReceiptHandle=m["ReceiptHandle"])


if __name__ == "__main__":
    main()
