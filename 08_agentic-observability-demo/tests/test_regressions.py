"""Regression tests: one test for each bug we found and fixed.

When you fix a bug, add a test here that would have caught it.
Keep the short story of the bug in the docstring, so the next person knows why the test exists.
"""
import pytest

from app.agent import NO_ANSWER, choose_route
from app.logging_setup import request_id_var
from app.retriever import tokenize
from app.validation import ValidationError


def test_bug_001_whitespace_question_reached_the_llm(agent, fake_llm):
    """A question with only spaces passed validation and we paid for an LLM call that returned nonsense."""
    with pytest.raises(ValidationError):
        agent.ask("     ")
    assert fake_llm.calls == []


def test_bug_002_punctuation_stopped_keyword_match(retriever):
    """'refund?' did not match 'refund' because we split on spaces only."""
    results = retriever.search("Refund?")
    assert results and results[0].id == "refund-policy"


def test_bug_003_repeated_words_inflated_scores(retriever):
    """'refund refund refund' gave a score of 3 and pushed weak documents to the top."""
    assert tokenize("refund refund refund") == {"refund"}
    assert retriever.search("refund refund refund")[0].score == 1


def test_bug_004_empty_context_made_llm_invent_answers(agent, fake_llm):
    """With no matching documents we still called the LLM, and it made up an answer from general knowledge."""
    response = agent.ask("Who won the football last night?")
    assert response.answer == NO_ANSWER
    assert fake_llm.calls == []


def test_bug_005_request_id_leaked_into_next_request(agent):
    """The request id was not reset, so logs after a request still showed the old id."""
    agent.ask("How do I reset my password?")
    assert request_id_var.get() == "-"


def test_bug_006_greeting_with_punctuation_used_retrieval(agent, fake_llm):
    """'Hello!' was not seen as small talk because of the '!'."""
    assert choose_route("Hello!") == "direct"
    assert agent.ask("Hello!").sources == []


def test_bug_007_api_key_in_error_message_reached_logs(retriever, json_logs):
    """An OpenAI error message included the API key, and we wrote it to the log file."""
    from app.agent import AgentError, SupportAgent
    from app.llm import LLMError
    from tests.conftest import FakeLLM

    leaky_llm = FakeLLM(error=LLMError("Incorrect API key provided: sk-proj-abc123def456ghi789"))
    agent = SupportAgent(llm=leaky_llm, retriever=retriever)
    with pytest.raises(AgentError):
        agent.ask("How do I reset my password?")

    for line in json_logs():
        assert "sk-proj-abc123def456ghi789" not in str(line)
