from app import config
from app.aws import opensearch

SOURCE_FIELDS = ["chunk_id", "doc_id", "source", "page", "text", "allowed_groups"]


def _to_hits(resp):
    hits = []
    for h in resp["hits"]["hits"]:
        doc = h["_source"]
        doc["score"] = h["_score"]
        hits.append(doc)
    return hits


def bm25_search(question, groups, k=config.BM25_K):
    body = {
        "size": k,
        "_source": SOURCE_FIELDS,
        "query": {
            "bool": {
                "must": [{"match": {"text": question}}],
                "filter": [{"terms": {"allowed_groups": groups}}],
            }
        },
    }
    return _to_hits(opensearch().search(index=config.INDEX_NAME, body=body))


def knn_search(vector, groups, k=config.KNN_K):
    # filter goes *inside* the knn clause (efficient filtering).
    # with a post filter we were getting less than k results back for users
    # in small groups - see docs/challenges-faced-during-development.md
    body = {
        "size": k,
        "_source": SOURCE_FIELDS,
        "query": {
            "knn": {
                "embedding": {
                    "vector": vector,
                    "k": k,
                    "filter": {"terms": {"allowed_groups": groups}},
                }
            }
        },
    }
    return _to_hits(opensearch().search(index=config.INDEX_NAME, body=body))
