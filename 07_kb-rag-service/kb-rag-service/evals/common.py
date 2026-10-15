import json
import os

from app.query.graph import build_graph
from app.users import get_groups

HERE = os.path.dirname(__file__)

# thresholds the CI job checks against. bump them up when we improve,
# never quietly lower them - add a note in docs/evals.md if you have to.
THRESHOLDS = {
    "recall_at_k": 0.90,
    "precision_at_k": 0.30,  # low on purpose: top 5 with mostly 1 relevant doc
    "faithfulness": 0.80,
    "answer_relevancy": 0.75,
    "contextual_precision": 0.70,
    "contextual_recall": 0.75,
}

LATENCY_BUDGET = {
    "ttft_p95_ms": 1500,
    "total_p95_ms": 4000,
    "retrieve_p95_ms": 400,
    "tps_p50_min": 30,
}


def load_golden(path=None):
    path = path or os.path.join(HERE, "golden_set.jsonl")
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


_graph = None


def run(question, user_id):
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph.invoke({
        "question": question,
        "user_id": user_id,
        "groups": get_groups(user_id),
        "timings": {},
    })
