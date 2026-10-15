"""Query pipeline as a single LangGraph agent.

    check_input -> retrieve -> fuse_and_acl -> rerank -> generate -> check_output
         |                                       |
         +-- blocked --> END                     +-- nothing found --> no_answer --> END

We looked at a tool calling loop (agent decides when to search again) but
for our questions one good hybrid search was enough and the loop doubled
latency. Keeping it a fixed graph makes it much easier to debug.
"""
import logging
import time
from typing import TypedDict

from langgraph.graph import END, StateGraph

from app import config
from app.embeddings import embed
from app.query import guardrails
from app.query.acl import acl_filter
from app.query.fusion import rrf
from app.query.generator import generate
from app.query.prompts import BLOCKED_ANSWER, NO_ANSWER
from app.query.reranker import rerank
from app.query.retriever import bm25_search, knn_search

log = logging.getLogger(__name__)


class RagState(TypedDict, total=False):
    question: str
    user_id: str
    groups: list
    clean_question: str
    bm25_hits: list
    knn_hits: list
    candidates: list
    docs: list
    answer: str
    citations: list
    blocked: bool
    timings: dict


def _timed(state, name, start):
    timings = dict(state.get("timings") or {})
    timings[name] = int((time.perf_counter() - start) * 1000)
    return timings


def check_input(state):
    q = state["question"]
    if guardrails.is_toxic(q):
        log.warning("blocked toxic question from %s", state["user_id"])
        return {"blocked": True, "answer": BLOCKED_ANSWER, "citations": []}

    pii = guardrails.find_pii(q)
    if pii:
        # don't send personal data to the embedding model or the llm
        log.info("redacted pii from question: %s", pii)
    return {"clean_question": guardrails.redact_pii(q), "blocked": False}


def retrieve(state):
    t = time.perf_counter()
    q = state["clean_question"]
    groups = state["groups"]

    bm25_hits = bm25_search(q, groups)
    knn_hits = knn_search(embed(q), groups)
    log.info("bm25=%d knn=%d", len(bm25_hits), len(knn_hits))
    return {"bm25_hits": bm25_hits, "knn_hits": knn_hits, "timings": _timed(state, "retrieve", t)}


def fuse_and_acl(state):
    fused = rrf([state["bm25_hits"], state["knn_hits"]], k=config.RRF_K)
    return {"candidates": acl_filter(fused, state["groups"])}


def rerank_node(state):
    t = time.perf_counter()
    docs = rerank(state["clean_question"], state["candidates"], top_k=config.TOP_K)
    return {"docs": docs, "timings": _timed(state, "rerank", t)}


def no_answer(state):
    return {"answer": NO_ANSWER, "citations": []}


def generate_node(state):
    answer, stats = generate(state["clean_question"], state["docs"])
    timings = dict(state.get("timings") or {})
    timings.update({"ttft": stats["ttft_ms"], "generate": stats["gen_ms"]})
    timings["tps"] = stats["tps"]

    citations = [
        {"n": i, "source": d["source"], "page": d.get("page"), "chunk_id": d["chunk_id"]}
        for i, d in enumerate(state["docs"], start=1)
    ]
    return {"answer": answer, "citations": citations, "timings": timings}


def check_output(state):
    answer = state["answer"]
    if guardrails.is_toxic(answer):
        log.error("toxic output blocked for question: %s", state["clean_question"][:100])
        return {"answer": BLOCKED_ANSWER, "citations": [], "blocked": True}
    if guardrails.find_pii(answer):
        log.warning("pii found in answer, redacting")
        answer = guardrails.redact_pii(answer)
    return {"answer": answer}


def build_graph():
    g = StateGraph(RagState)
    g.add_node("check_input", check_input)
    g.add_node("retrieve", retrieve)
    g.add_node("fuse_and_acl", fuse_and_acl)
    g.add_node("rerank", rerank_node)
    g.add_node("no_answer", no_answer)
    g.add_node("generate", generate_node)
    g.add_node("check_output", check_output)

    g.set_entry_point("check_input")
    g.add_conditional_edges(
        "check_input",
        lambda s: "end" if s.get("blocked") else "retrieve",
        {"end": END, "retrieve": "retrieve"},
    )
    g.add_edge("retrieve", "fuse_and_acl")
    g.add_edge("fuse_and_acl", "rerank")
    g.add_conditional_edges(
        "rerank",
        lambda s: "generate" if s.get("docs") else "no_answer",
        {"generate": "generate", "no_answer": "no_answer"},
    )
    g.add_edge("no_answer", END)
    g.add_edge("generate", "check_output")
    g.add_edge("check_output", END)
    return g.compile()
