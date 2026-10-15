import io
import json
import logging
import os

# Turn LangSmith tracing off for local tests, before the app is imported.
# Tests must not send data to LangSmith or need an API key.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

import pytest  # noqa: E402

from app.agent import SupportAgent  # noqa: E402
from app.config import PROJECT_ROOT  # noqa: E402
from app.llm import LLMResult  # noqa: E402
from app.logging_setup import JsonFormatter  # noqa: E402
from app.retriever import KeywordRetriever, load_documents  # noqa: E402

DOCS_DIR = PROJECT_ROOT / "data" / "docs"


class FakeLLM:
    """Stands in for OpenAI. Remembers every call so tests can check what was sent."""

    def __init__(self, answer="This is a fake answer.", error=None):
        self.answer = answer
        self.error = error
        self.calls = []

    def complete(self, system_prompt, user_prompt):
        self.calls.append({"system": system_prompt, "user": user_prompt})
        if self.error:
            raise self.error
        return LLMResult(text=self.answer, model="fake-model", input_tokens=120, output_tokens=30)


@pytest.fixture
def documents():
    return load_documents(DOCS_DIR)


@pytest.fixture
def retriever(documents):
    return KeywordRetriever(documents, top_k=2)


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def agent(fake_llm, retriever):
    return SupportAgent(llm=fake_llm, retriever=retriever, prompt_version="v1")


@pytest.fixture
def json_logs():
    """Capture the app's logs as parsed JSON dicts.

    Usage:  lines = json_logs()  ->  list of dicts
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("app")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    def read():
        return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]

    yield read

    logger.removeHandler(handler)
    logger.setLevel(old_level)
