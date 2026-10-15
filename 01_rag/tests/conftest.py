import hashlib
import math
import re
from pathlib import Path

import pytest

from rag.config import Settings

SAMPLE_DOCS = Path(__file__).parent.parent / "data" / "sample_docs"


class FakeEmbedder:
    """Turns text into a simple word-count vector. Good enough for tests, no API needed."""

    size = 256

    def embed_texts(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, query):
        return self._embed(query)

    def _embed(self, text):
        vector = [0.0] * self.size
        for word in re.findall(r"[a-z]+", text.lower()):
            index = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.size
            vector[index] += 1.0
        length = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / length for value in vector]


class FakeGenerator:
    def generate_answer(self, question, matches):
        return f"answer based on {len(matches)} chunks"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        openai_api_key="",
        embedding_model="test",
        chat_model="test",
        db_path=str(tmp_path / "db"),
        collection_name="test",
        chunk_size=300,
        chunk_overlap=50,
        top_k=3,
        min_relevance=0.05,
        log_level="WARNING",
    )
