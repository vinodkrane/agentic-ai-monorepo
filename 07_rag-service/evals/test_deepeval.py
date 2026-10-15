"""Answer quality evals with deepeval, judged by Claude on Bedrock.

These call the LLM twice per case (pipeline + judge) so they run nightly,
not on every PR.

    deepeval test run evals/test_deepeval.py
    # or plain pytest
    pytest evals/test_deepeval.py -m llm
"""
import pytest
from deepeval import assert_test
from deepeval.metrics import (
    AnswerRelevancyMetric,
    ContextualPrecisionMetric,
    ContextualRecallMetric,
    FaithfulnessMetric,
)
from deepeval.test_case import LLMTestCase

from evals.common import THRESHOLDS, load_golden, run
from evals.judge import BedrockJudge

judge = BedrockJudge()

ROWS = [r for r in load_golden() if r["expected_sources"]]


def metrics():
    return [
        ContextualRecallMetric(threshold=THRESHOLDS["contextual_recall"], model=judge),
        ContextualPrecisionMetric(threshold=THRESHOLDS["contextual_precision"], model=judge),
        FaithfulnessMetric(threshold=THRESHOLDS["faithfulness"], model=judge),
        AnswerRelevancyMetric(threshold=THRESHOLDS["answer_relevancy"], model=judge),
    ]


@pytest.mark.llm
@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_answer_quality(row):
    result = run(row["question"], row["user_id"])

    case = LLMTestCase(
        input=row["question"],
        actual_output=result["answer"],
        expected_output=row["ground_truth"],
        retrieval_context=[d["text"] for d in result.get("docs", [])],
    )
    assert_test(case, metrics())
