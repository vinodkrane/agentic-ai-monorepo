import json
from pathlib import Path

import pytest

from app.agent import NO_ANSWER, choose_route
from eval.compare_runs import compare_scores
from eval.create_datasets import load_dataset_file
from eval.evaluators import context_recall, correctness, is_refusal, refusal_check, retrieval_hit, route_match

DATASETS = Path(__file__).resolve().parent.parent / "eval" / "datasets"


# ---------- evaluators ----------

def test_correctness_full_match():
    result = correctness({"answer": "You have 14 days to ask."}, {"must_include": ["14 days"]})
    assert result == {"key": "correctness", "score": 1.0, "comment": "all facts found"}


def test_correctness_partial_match():
    result = correctness({"answer": "It takes 5 days."}, {"must_include": ["5", "7"]})
    assert result["score"] == 0.5
    assert "7" in result["comment"]


def test_correctness_accepts_alternatives():
    result = correctness({"answer": "You can use TWO screens."}, {"must_include": ["two | 2"]})
    assert result["score"] == 1.0


def test_correctness_with_nothing_required_is_full_score():
    assert correctness({"answer": "Hi!"}, {"must_include": []})["score"] == 1.0


def test_context_recall_checks_retrieved_text_not_answer():
    outputs = {"answer": "14 days", "contexts": ["Some unrelated text."]}
    assert context_recall(outputs, {"must_include": ["14 days"]})["score"] == 0.0


def test_retrieval_hit():
    reference = {"expected_source": "refund-policy"}
    assert retrieval_hit({"sources": ["refund-policy", "downloads"]}, reference)["score"] == 1.0
    assert retrieval_hit({"sources": ["downloads"]}, reference)["score"] == 0.0
    assert retrieval_hit({}, reference)["score"] == 0.0


def test_route_match():
    assert route_match({"route": "direct"}, {"expected_route": "direct"})["score"] == 1.0
    assert route_match({"route": "retrieve"}, {"expected_route": "direct"})["score"] == 0.0


@pytest.mark.parametrize("answer, expected", [
    (NO_ANSWER, True),
    ("I don't know based on the help documents.", True),
    ("Premium costs £14.99.", False),
])
def test_is_refusal(answer, expected):
    assert is_refusal(answer) is expected


def test_refusal_check_both_directions():
    assert refusal_check({"answer": NO_ANSWER}, {"expected_refusal": True})["score"] == 1.0
    assert refusal_check({"answer": "Paris"}, {"expected_refusal": True})["score"] == 0.0
    assert refusal_check({"answer": NO_ANSWER}, {"expected_refusal": False})["score"] == 0.0


# ---------- datasets ----------

@pytest.mark.parametrize("file_name", ["rag_dataset.json", "agent_dataset.json"])
def test_dataset_files_are_valid(file_name):
    data = load_dataset_file(DATASETS / file_name)
    assert data["name"]
    assert len(data["examples"]) >= 5


def test_rag_dataset_sources_exist(documents):
    doc_ids = {doc.id for doc in documents}
    data = load_dataset_file(DATASETS / "rag_dataset.json")
    for example in data["examples"]:
        assert example["outputs"]["expected_source"] in doc_ids


def test_rag_dataset_retrieval_works_without_llm(retriever):
    """Retrieval is free, so we can check every RAG example offline."""
    data = load_dataset_file(DATASETS / "rag_dataset.json")
    for example in data["examples"]:
        found = [doc.id for doc in retriever.search(example["inputs"]["question"])]
        assert example["outputs"]["expected_source"] in found, example["inputs"]["question"]


def test_agent_dataset_routes_match_choose_route():
    data = json.loads((DATASETS / "agent_dataset.json").read_text(encoding="utf-8"))
    for example in data["examples"]:
        assert choose_route(example["inputs"]["question"]) == example["outputs"]["expected_route"]


# ---------- comparing experiments ----------

def test_compare_scores_flags_drops():
    rows = compare_scores({"correctness": 0.9, "retrieval_hit": 1.0}, {"correctness": 0.7, "retrieval_hit": 1.0})
    status = {row[0]: row[4] for row in rows}
    assert status == {"correctness": "WORSE", "retrieval_hit": "SAME"}


def test_compare_scores_small_changes_are_same():
    rows = compare_scores({"correctness": 0.80}, {"correctness": 0.78}, tolerance=0.05)
    assert rows[0][4] == "SAME"


def test_compare_scores_new_and_removed_metrics():
    rows = compare_scores({"old_metric": 1.0}, {"llm_judge": 0.8})
    status = {row[0]: row[4] for row in rows}
    assert status == {"llm_judge": "NEW", "old_metric": "REMOVED"}
