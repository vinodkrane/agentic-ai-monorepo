import os

from dotenv import load_dotenv

load_dotenv()


def _get(name, default=None):
    return os.environ.get(name, default)


AWS_REGION = _get("AWS_REGION", "eu-west-2")

# S3 / SQS
DOCS_BUCKET = _get("DOCS_BUCKET", "kb-rag-docs-dev")
INGEST_QUEUE_URL = _get("INGEST_QUEUE_URL", "")
# set this when running against localstack, leave empty in AWS
AWS_ENDPOINT_URL = _get("AWS_ENDPOINT_URL") or None
# worker / queue settings
# must match maxReceiveCount on the queue redrive policy (infra/template.yaml)
MAX_RECEIVE_COUNT = int(_get("MAX_RECEIVE_COUNT", "3"))
VISIBILITY_TIMEOUT = int(_get("VISIBILITY_TIMEOUT", "300"))
# extend visibility this often while a doc is being processed, keep it well under VISIBILITY_TIMEOUT
HEARTBEAT_SECONDS = int(_get("HEARTBEAT_SECONDS", "60"))
# failed message comes back after RETRY_DELAY_SECONDS * attempt
RETRY_DELAY_SECONDS = int(_get("RETRY_DELAY_SECONDS", "60"))
POLL_WAIT_SECONDS = int(_get("POLL_WAIT_SECONDS", "20"))

# DynamoDB table for document ingest status
STATUS_TABLE = _get("STATUS_TABLE", "kb-rag-doc-status-dev")
# anything in "processing" longer than this is treated as stuck
STUCK_AFTER_MINUTES = int(_get("STUCK_AFTER_MINUTES", "20"))

# OpenSearch
OPENSEARCH_HOST = _get("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(_get("OPENSEARCH_PORT", "9200"))
OPENSEARCH_USE_IAM = _get("OPENSEARCH_USE_IAM", "false").lower() == "true"
INDEX_NAME = _get("INDEX_NAME", "kb-chunks-v1")

# Bedrock models
EMBED_MODEL_ID = _get("EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
EMBED_DIM = int(_get("EMBED_DIM", "1024"))
LLM_MODEL_ID = _get("LLM_MODEL_ID", "anthropic.claude-3-5-sonnet-20240620-v1:0")
JUDGE_MODEL_ID = _get("JUDGE_MODEL_ID", LLM_MODEL_ID)

# reranker runs locally (cross encoder) inside the API container
RERANK_MODEL = _get("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANK_ENABLED = _get("RERANK_ENABLED", "true").lower() == "true"

# chunking
CHUNK_SIZE = int(_get("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(_get("CHUNK_OVERLAP", "100"))

# retrieval knobs - tuned against the golden set, see docs/evals.md
BM25_K = int(_get("BM25_K", "20"))
KNN_K = int(_get("KNN_K", "20"))
RRF_K = int(_get("RRF_K", "60"))
TOP_K = int(_get("TOP_K", "5"))

# uploads
MAX_UPLOAD_MB = int(_get("MAX_UPLOAD_MB", "20"))
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}

USERS_FILE = _get("USERS_FILE", "data/users.json")
