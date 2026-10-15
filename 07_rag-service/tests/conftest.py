import os

import boto3
import pytest
from moto import mock_aws

from app import config


@pytest.fixture
def aws(monkeypatch):
    """Fake S3 bucket + status table with moto. Nothing leaves the machine."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", config.AWS_REGION)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    # if someone has a .env pointing at localstack, ignore it in tests
    monkeypatch.setattr(config, "AWS_ENDPOINT_URL", None)

    with mock_aws():
        s3 = boto3.client("s3", region_name=config.AWS_REGION)
        s3.create_bucket(
            Bucket=config.DOCS_BUCKET,
            CreateBucketConfiguration={"LocationConstraint": config.AWS_REGION},
        )
        queue_url = boto3.client("sqs", region_name=config.AWS_REGION).create_queue(
            QueueName="kb-rag-ingest-test")["QueueUrl"]
        monkeypatch.setattr(config, "INGEST_QUEUE_URL", queue_url)

        boto3.client("dynamodb", region_name=config.AWS_REGION).create_table(
            TableName=config.STATUS_TABLE,
            AttributeDefinitions=[{"AttributeName": "doc_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "doc_id", "KeyType": "HASH"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield s3


# users.json path is relative, make sure tests work from any folder
os.chdir(os.path.dirname(os.path.dirname(__file__)))
