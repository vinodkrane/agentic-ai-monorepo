import pytest

from app.agent import NO_ANSWER, AgentError, AgentResponse, SupportAgent, choose_route
from app.llm import LLMError
from app.validation import ValidationError
from tests.conftest import FakeLLM


# ---------- response structure ----------

def test_response_has_expected_structure(agent):
    response = agent.ask("How many days do I have to ask for a refund?")

    assert isinstance(response, AgentResponse)
    data = response.to_dict()
    for key in ("request_id", "question", "answer", "route", "sources", "contexts",
                "input_tokens", "output_tokens", "latency_ms", "trace_id"):
        assert key in data

    assert response.answer == "This is a fake answer."
    assert response.route == "retrieve"
    assert response.sources[0] == "refund-policy"
    assert len(response.contexts) == len(response.sources)
    assert response.input_tokens == 120
    assert response.output_tokens == 30
    assert response.latency_ms >= 0


def test_request_id_can_be_passed_in(agent):
    assert agent.ask("refund?", request_id="abc123").request_id == "abc123"


def test_each_request_gets_its_own_id(agent):
    first = agent.ask("refund?")
    second = agent.ask("refund?")
    assert first.request_id != second.request_id


# ---------- routing ----------

@pytest.mark.parametrize("question, route", [
    ("hello", "direct"),
    ("Thank you!", "direct"),
    ("How do I reset my password?", "retrieve"),
])
def test_choose_route(question, route):
    assert choose_route(question) == route


def test_small_talk_does_not_search_documents(agent, fake_llm):
    response = agent.ask("hello")
    assert response.route == "direct"
    assert response.sources == []
    assert len(fake_llm.calls) == 1


def test_retrieved_documents_are_sent_to_the_llm(agent, fake_llm):
    agent.ask("How much does the Premium plan cost?")
    prompt = fake_llm.calls[0]["user"]
    assert "[subscription-plans]" in prompt
    assert "£14.99" in prompt


def test_prompt_version_changes_system_prompt(fake_llm, retriever):
    agent = SupportAgent(llm=fake_llm, retriever=retriever, prompt_version="v2")
    agent.ask("How much does the Premium plan cost?")
    assert "ONLY" in fake_llm.calls[0]["system"]


def test_no_matching_documents_gives_fallback_without_llm_call(agent, fake_llm):
    response = agent.ask("What is the capital of France?")
    assert response.answer == NO_ANSWER
    assert response.sources == []
    assert fake_llm.calls == []


# ---------- error handling ----------

def test_invalid_question_raises_validation_error_and_logs_warning(agent, json_logs):
    with pytest.raises(ValidationError):
        agent.ask("   ")

    warnings = [line for line in json_logs() if line["level"] == "WARNING"]
    assert warnings[0]["status"] == "rejected"
    assert warnings[0]["error_type"] == "ValidationError"


def test_llm_failure_becomes_agent_error_and_logs_error(retriever, json_logs):
    broken_llm = FakeLLM(error=LLMError("OpenAI call failed: timeout"))
    agent = SupportAgent(llm=broken_llm, retriever=retriever)

    with pytest.raises(AgentError, match="not available"):
        agent.ask("How do I reset my password?")

    errors = [line for line in json_logs() if line["level"] == "ERROR"]
    assert len(errors) == 1
    assert errors[0]["status"] == "failed"
    assert errors[0]["exception"]["type"] == "LLMError"
    assert "timeout" in errors[0]["exception"]["message"]


def test_unexpected_error_is_wrapped(retriever):
    agent = SupportAgent(llm=FakeLLM(error=RuntimeError("boom")), retriever=retriever)
    with pytest.raises(AgentError, match="Something went wrong"):
        agent.ask("How do I reset my password?")


def test_unknown_prompt_version_fails_clearly(fake_llm, retriever):
    agent = SupportAgent(llm=fake_llm, retriever=retriever, prompt_version="v99")
    with pytest.raises(AgentError):
        agent.ask("How do I reset my password?")


# ---------- logging from the agent ----------

def test_successful_request_logs_each_step(agent, json_logs):
    response = agent.ask("How do I reset my password?")
    lines = json_logs()

    operations = [line["operation"] for line in lines]
    assert operations == ["agent.ask", "agent.route", "agent.retrieve", "agent.llm", "agent.ask"]
    assert all(line["request_id"] == response.request_id for line in lines)
    assert lines[-1]["status"] == "success"
    assert lines[-1]["duration_ms"] >= 0


def test_question_text_is_not_logged_by_default(agent, json_logs):
    agent.ask("How do I reset my password?")
    for line in json_logs():
        assert "question" not in line
        assert "reset my password" not in line["message"]
