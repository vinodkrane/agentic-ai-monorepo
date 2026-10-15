import logging

from opensearchpy import helpers

from app import config
from app.aws import opensearch

log = logging.getLogger(__name__)

INDEX_BODY = {
    "settings": {
        "index": {
            "knn": True,
            "number_of_shards": 1,
            "number_of_replicas": 1,
        }
    },
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "page": {"type": "integer"},
            "chunk_index": {"type": "integer"},
            "allowed_groups": {"type": "keyword"},
            "text": {"type": "text", "analyzer": "english"},
            "embedding": {
                "type": "knn_vector",
                "dimension": config.EMBED_DIM,
                "method": {
                    "name": "hnsw",
                    "engine": "faiss",
                    "space_type": "innerproduct",  # titan vectors are normalised
                    "parameters": {"m": 16, "ef_construction": 128},
                },
            },
        }
    },
}


def ensure_index():
    os_client = opensearch()
    if not os_client.indices.exists(index=config.INDEX_NAME):
        log.info("creating index %s", config.INDEX_NAME)
        os_client.indices.create(index=config.INDEX_NAME, body=INDEX_BODY)


def delete_doc(doc_id):
    """Remove old chunks before re-indexing, otherwise a re-upload leaves
    stale chunks behind when the new version has fewer chunks."""
    resp = opensearch().delete_by_query(
        index=config.INDEX_NAME,
        body={"query": {"term": {"doc_id": doc_id}}},
        refresh=True,
        conflicts="proceed",
    )
    if resp.get("deleted"):
        log.info("deleted %d old chunks for %s", resp["deleted"], doc_id)


def index_chunks(chunks, vectors):
    actions = []
    for chunk, vec in zip(chunks, vectors):
        actions.append({
            "_index": config.INDEX_NAME,
            "_id": chunk["chunk_id"],
            "_source": {**chunk, "embedding": vec},
        })
    ok, errors = helpers.bulk(opensearch(), actions, raise_on_error=False)
    if errors:
        log.error("bulk index had %d errors, first: %s", len(errors), errors[0])
        raise RuntimeError("indexing failed")
    return ok
