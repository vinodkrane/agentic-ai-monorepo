"""Graph wiring tests. Retrieval and the LLM are stubbed so no AWS needed."""
import pytest

from app.query import graph as g


@pytest.fixture
def stubbed(monkeypatch):
    docs = [
        {"chunk_id": "d1-0000", "doc_id": "d1", "source": "leave.md", "page": 1,
         "text": "Full time staff get 25 days.", "allowed_groups": ["all-staff"]},
        {"chunk_id": "d2-0000", "doc_id": "d2", "source": "oncall.md", "page": 1,
         "text": "Ack P1 in 5 minutes.", "allowed_groups": ["platform-eng"]},
    ]
    calls = {"llm": 0}

    monkeypatch.setattr(g, "embed", lambda q: [0.0] * 4)
    # retriever "forgets" the ACL filter so we can check the re-check catches it
    monkeypatch.setattr(g, "bm25_search", lambda q, groups: docs)
    monkeypatch.setattr(g, "knn_search", lambda v, groups: docs[:1])
    monkeypatch.setattr(g, "rerank", lambda q, chunks, top_k: chunks[:top_k])

    def fake_generate(q, chunks):
        calls["llm"] += 1
        stats = {"ttft_ms": 10, "gen_ms": 50, "output_tokens": 10, "tps": 50.0}
        return "You get 25 days [1]. Ask jane@example.com", stats

    monkeypatch.setattr(g, "generate", fake_generate)
    return calls


def invoke(question, groups):
    return g.build_graph().invoke({"question": question, "user_id": "u", "groups": groups, "timings": {}})


def test_happy_path(stubbed):
    out = invoke("how much leave?", ["all-staff"])
    assert out["answer"].startswith("You get 25 days")
    assert [c["source"] for c in out["citations"]] == ["leave.md"]  # oncall.md removed by acl
    assert "ttft" in out["timings"] and "retrieve" in out["timings"]


def test_output_pii_is_redacted(stubbed):
    out = invoke("how much leave?", ["all-staff"])
    assert "jane@example.com" not in out["answer"]


def test_toxic_question_never_hits_llm(stubbed):
    out = invoke("kys", ["all-staff"])
    assert out["blocked"] is True
    assert stubbed["llm"] == 0


def test_no_docs_gives_no_answer(stubbed):
    out = invoke("anything", ["nobody"])
    assert "couldn't find" in out["answer"]
    assert stubbed["llm"] == 0
