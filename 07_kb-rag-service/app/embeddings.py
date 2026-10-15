import json
import logging

from app import config
from app.aws import client

log = logging.getLogger(__name__)

# titan v2 takes up to 8k tokens, we are way under with 800 char chunks
# but cap anyway in case someone bumps CHUNK_SIZE
MAX_CHARS = 20000

_bedrock = None


def _runtime():
    global _bedrock
    if _bedrock is None:
        _bedrock = client("bedrock-runtime")
    return _bedrock


def embed(text):
    resp = _runtime().invoke_model(
        modelId=config.EMBED_MODEL_ID,
        body=json.dumps({
            "inputText": text[:MAX_CHARS],
            "dimensions": config.EMBED_DIM,
            "normalize": True,
        }),
    )
    return json.loads(resp["body"].read())["embedding"]


def embed_many(texts):
    # titan has no batch endpoint on invoke_model, so this is a plain loop.
    # good enough for our doc sizes, revisit with batch inference if needed
    vectors = []
    for i, t in enumerate(texts):
        vectors.append(embed(t))
        if i and i % 50 == 0:
            log.info("embedded %d/%d", i, len(texts))
    return vectors
