def rrf(result_lists, k=60):
    """Reciprocal rank fusion.

    BM25 and kNN scores are on completely different scales so we only use
    the rank. score = sum(1 / (k + rank)) over every list the chunk shows up in.
    """
    scores = {}
    docs = {}
    for results in result_lists:
        for rank, hit in enumerate(results, start=1):
            cid = hit["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            docs.setdefault(cid, hit)

    ordered = sorted(scores, key=lambda c: scores[c], reverse=True)
    fused = []
    for cid in ordered:
        hit = dict(docs[cid])
        hit["rrf_score"] = scores[cid]
        fused.append(hit)
    return fused
