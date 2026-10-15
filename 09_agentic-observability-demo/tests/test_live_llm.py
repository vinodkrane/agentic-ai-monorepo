"""Live tests that call the real OpenAI API.

They are skipped by default (see pytest.ini). Run them on purpose with:
    pytest -m live
They need OPENAI_API_KEY in .env and cost a tiny amount of money.
"""
import pytest

from app.agent import NO_ANSWER, build_agent
from app.config import load_settings

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_agent():
    settings = load_settings()
    if not settings.openai_api_key:
        pytest.skip("OPENAI_API_KEY is not set")
    return build_agent(settings)


def test_live_rag_answer_contains_fact(live_agent):
    response = live_agent.ask("How many days do I have to ask for a refund?")
    assert "14" in response.answer
    assert "refund-policy" in response.sources
    assert response.input_tokens > 0
    assert response.output_tokens > 0


def test_live_small_talk(live_agent):
    response = live_agent.ask("hello")
    assert response.route == "direct"
    assert response.answer


def test_live_out_of_scope_question_is_not_answered(live_agent):
    response = live_agent.ask("What is the capital of France?")
    assert response.answer == NO_ANSWER
