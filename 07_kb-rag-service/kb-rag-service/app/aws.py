"""Small helpers so every module creates AWS clients the same way."""
import boto3
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from app import config

_os_client = None


# only these go to localstack when AWS_ENDPOINT_URL is set
LOCAL_SERVICES = ("s3", "sqs", "dynamodb")


def _endpoint(service):
    return config.AWS_ENDPOINT_URL if service in LOCAL_SERVICES else None


def client(service):
    return boto3.client(service, region_name=config.AWS_REGION, endpoint_url=_endpoint(service))


def table(name):
    dynamodb = boto3.resource("dynamodb", region_name=config.AWS_REGION, endpoint_url=_endpoint("dynamodb"))
    return dynamodb.Table(name)


def opensearch():
    global _os_client
    if _os_client is not None:
        return _os_client

    kwargs = dict(
        hosts=[{"host": config.OPENSEARCH_HOST, "port": config.OPENSEARCH_PORT}],
        connection_class=RequestsHttpConnection,
        timeout=30,
    )
    if config.OPENSEARCH_USE_IAM:
        creds = boto3.Session().get_credentials()
        kwargs["http_auth"] = AWSV4SignerAuth(creds, config.AWS_REGION, "es")
        kwargs["use_ssl"] = True
        kwargs["verify_certs"] = True
    else:
        # local docker opensearch, security plugin disabled
        kwargs["use_ssl"] = False

    _os_client = OpenSearch(**kwargs)
    return _os_client
