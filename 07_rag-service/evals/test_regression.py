"""Retrieval regression tests against the golden set.

No LLM calls here except the last test, so this is cheap enough to run
on every PR. Needs the eval index seeded (scripts/seed_local.sh).

    pytest evals/test_regression.py -v
"""
import pytest

from app import config
from app.embeddings import embed
from app.query.acl import acl_filter
from app.query.fusion import rrf
from app.query.prompts import NO_ANSWER
from app.query.reranker import rerank
from app.query.retriever import bm25_search, knn_search
from app.users import get_groups
from evals.common import THRESHOLDS, load_golden, run

GOLDEN = load_golden()
ANSWERABLE = [r for r in GOLDEN if r["expected_sources"]]
ACL_CASES = [r for r in GOLDEN if r.get("must_not_sources")]


def retrieve_top_k(question, user_id, k=config.TOP_K):
    groups = get_groups(user_id)
    fused = rrf([bm25_search(question, groups), knn_search(embed(question), groups)], k=config.RRF_K)
    return rerank(question, acl_filter(fused, groups), top_k=k)


def recall_and_precision(row):
    docs = retrieve_top_k(row["question"], row["user_id"])
    got = [d["source"] for d in docs]
    expected = set(row["expected_sources"])

    recall = len(expected.intersection(got)) / len(expected)
    precision = sum(1 for s in got if s in expected) / len(got) if got else 0.0
    return recall, precision


def test_retrieval_recall_and_precision():
    recalls, precisions, misses = [], [], []
    for row in ANSWERABLE:
        r, p = recall_and_precision(row)
        recalls.append(r)
        precisions.append(p)
        if r < 1.0:
            misses.append(row["id"])

    avg_recall = sum(recalls) / len(recalls)
    avg_precision = sum(precisions) / len(precisions)
    print(f"\nrecall@{config.TOP_K}={avg_recall:.2f} precision@{config.TOP_K}={avg_precision:.2f} misses={misses}")

    assert avg_recall >= THRESHOLDS["recall_at_k"], f"recall dropped, missed: {misses}"
    assert avg_precision >= THRESHOLDS["precision_at_k"]


@pytest.mark.parametrize("row", ACL_CASES, ids=[r["id"] for r in ACL_CASES])
def test_acl_no_leak_in_retrieval(row):
    docs = retrieve_top_k(row["question"], row["user_id"], k=20)
    leaked = [d["source"] for d in docs if d["source"] in row["must_not_sources"]]
    assert not leaked, f"user {row['user_id']} could see {leaked}"


@pytest.mark.llm
@pytest.mark.parametrize("row", ACL_CASES, ids=[r["id"] for r in ACL_CASES])
def test_acl_no_leak_in_answer(row):
    result = run(row["question"], row["user_id"])
    sources = [c["source"] for c in result.get("citations", [])]
    assert not set(sources).intersection(row["must_not_sources"])
    # model should fall back to the no answer message
    assert "couldn't find" in result["answer"].lower() or result["answer"] == NO_ANSWER
