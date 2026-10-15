import logging

from app import config

log = logging.getLogger(__name__)

_model = None


def _load():
    global _model
    if _model is None:
        from sentence_transformers import CrossEncoder
        log.info("loading reranker %s", config.RERANK_MODEL)
        _model = CrossEncoder(config.RERANK_MODEL, max_length=512)
    return _model


def rerank(question, chunks, top_k=config.TOP_K):
    if not chunks:
        return []
    if not config.RERANK_ENABLED:
        return chunks[:top_k]

    # only rerank the head of the fused list, the tail almost never wins
    # and the cross encoder is the slowest part of retrieval
    candidates = chunks[:20]
    scores = _load().predict([(question, c["text"]) for c in candidates])

    for c, s in zip(candidates, scores):
        c["rerank_score"] = float(s)
    candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
    return candidates[:top_k]
