"""The support agent.

Flow for one question:
    validate -> choose route -> (search docs) -> call LLM -> return AgentResponse

The agent makes one decision: does this question need the help documents or not?
It is kept simple on purpose. What matters here is that every step is traced
(LangSmith) and logged (JSON logs).
"""
import logging
import time
from dataclasses import asdict, dataclass, field

from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from app.llm import LLMError, OpenAIChatModel
from app.logging_setup import new_request_id, request_id_var
from app.prompts import SMALL_TALK_PROMPT, build_user_prompt, get_system_prompt
from app.retriever import KeywordRetriever, load_documents
from app.validation import ValidationError, validate_question

logger = logging.getLogger("app.agent")

NO_ANSWER = "Sorry, I could not find this in the StreamBox help documents."

SMALL_TALK = {"hi", "hello", "hey", "thanks", "thank you", "who are you", "what can you do"}


class AgentError(Exception):
    """Something went wrong while answering. The message is safe to show to the user."""


@dataclass
class AgentResponse:
    request_id: str
    question: str
    answer: str
    route: str
    sources: list = field(default_factory=list)
    contexts: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    trace_id: str = ""

    def to_dict(self):
        return asdict(self)


def choose_route(question):
    """'direct' for small talk, 'retrieve' for everything else."""
    text = question.lower().strip(" ?!.")
    return "direct" if text in SMALL_TALK else "retrieve"


def _ms_since(start):
    return round((time.perf_counter() - start) * 1000, 1)


class SupportAgent:
    def __init__(self, llm, retriever, prompt_version="v1", max_question_chars=500, log_questions=False):
        self.llm = llm
        self.retriever = retriever
        self.prompt_version = prompt_version
        self.max_question_chars = max_question_chars
        self.log_questions = log_questions

    def ask(self, question, request_id=None):
        """Public entry point. Sets the request id, logs start/end, and turns errors into AgentError."""
        request_id = request_id or new_request_id()
        token = request_id_var.set(request_id)
        start = time.perf_counter()

        start_fields = {"operation": "agent.ask", "status": "started", "prompt_version": self.prompt_version}
        if isinstance(question, str):
            start_fields["question_chars"] = len(question)
            if self.log_questions:
                start_fields["question"] = question
        logger.info("Request received", extra=start_fields)

        try:
            response = self._run(
                question,
                request_id,
                langsmith_extra={
                    "metadata": {"request_id": request_id, "prompt_version": self.prompt_version},
                    "tags": ["support-agent", f"prompt-{self.prompt_version}"],
                },
            )
        except ValidationError as exc:
            logger.warning(
                "Question rejected",
                extra={"operation": "agent.ask", "status": "rejected", "error_type": "ValidationError",
                       "error_message": str(exc), "duration_ms": _ms_since(start)},
            )
            raise
        except LLMError as exc:
            logger.error(
                "LLM call failed",
                exc_info=True,
                extra={"operation": "agent.ask", "status": "failed", "error_type": "LLMError",
                       "duration_ms": _ms_since(start)},
            )
            raise AgentError("The AI service is not available right now. Please try again later.") from exc
        except Exception as exc:
            logger.error(
                "Unexpected error",
                exc_info=True,
                extra={"operation": "agent.ask", "status": "failed", "error_type": type(exc).__name__,
                       "duration_ms": _ms_since(start)},
            )
            raise AgentError("Something went wrong while answering your question.") from exc
        else:
            response.latency_ms = _ms_since(start)
            logger.info(
                "Request completed",
                extra={"operation": "agent.ask", "status": "success", "route": response.route,
                       "sources": response.sources, "input_tokens": response.input_tokens,
                       "output_tokens": response.output_tokens, "duration_ms": response.latency_ms,
                       "trace_id": response.trace_id},
            )
            return response
        finally:
            request_id_var.reset(token)

    @traceable(name="support_agent", run_type="chain")
    def _run(self, question, request_id):
        run = get_current_run_tree()
        trace_id = str(run.trace_id) if run else ""

        clean_question = validate_question(question, self.max_question_chars)
        route = choose_route(clean_question)
        logger.info("Route chosen", extra={"operation": "agent.route", "status": "success", "route": route})

        if route == "direct":
            result = self._call_llm(SMALL_TALK_PROMPT, clean_question)
            return AgentResponse(
                request_id=request_id, question=clean_question, answer=result.text, route=route,
                input_tokens=result.input_tokens, output_tokens=result.output_tokens, trace_id=trace_id,
            )

        documents = self._retrieve(clean_question)
        if not documents:
            # Nothing relevant: answer without calling the LLM. Saves money and avoids made-up answers.
            logger.warning("No documents matched", extra={"operation": "agent.retrieve", "status": "empty"})
            return AgentResponse(
                request_id=request_id, question=clean_question, answer=NO_ANSWER, route=route, trace_id=trace_id,
            )

        user_prompt = build_user_prompt(clean_question, documents)
        result = self._call_llm(get_system_prompt(self.prompt_version), user_prompt)
        return AgentResponse(
            request_id=request_id,
            question=clean_question,
            answer=result.text,
            route=route,
            sources=[doc.id for doc in documents],
            contexts=[doc.text for doc in documents],
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            trace_id=trace_id,
        )

    def _retrieve(self, question):
        start = time.perf_counter()
        documents = self.retriever.search(question)
        logger.info(
            "Documents retrieved",
            extra={"operation": "agent.retrieve", "status": "success", "doc_count": len(documents),
                   "sources": [doc.id for doc in documents], "duration_ms": _ms_since(start)},
        )
        return documents

    def _call_llm(self, system_prompt, user_prompt):
        start = time.perf_counter()
        result = self.llm.complete(system_prompt, user_prompt)
        logger.info(
            "LLM call finished",
            extra={"operation": "agent.llm", "status": "success", "model": result.model,
                   "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                   "duration_ms": _ms_since(start)},
        )
        return result


def build_agent(settings, llm=None):
    """Create the agent from settings. Pass `llm` to use a fake model (tests do this)."""
    documents = load_documents(settings.docs_dir)
    retriever = KeywordRetriever(documents, top_k=settings.top_k)
    if llm is None:
        llm = OpenAIChatModel(api_key=settings.openai_api_key, model=settings.openai_model)
    return SupportAgent(
        llm=llm,
        retriever=retriever,
        prompt_version=settings.prompt_version,
        max_question_chars=settings.max_question_chars,
        log_questions=settings.log_questions,
    )
