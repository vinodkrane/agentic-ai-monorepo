"""Check the Embedder and Generator with a stub client (no real API calls)."""

from types import SimpleNamespace

from rag.embedder import BATCH_SIZE, Embedder
from rag.generator import NO_CONTEXT_ANSWER, Generator


class StubClient:
    def __init__(self):
        self.embedding_calls = 0
        self.last_messages = None
        self.embeddings = SimpleNamespace(create=self._create_embeddings)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat))

    def _create_embeddings(self, model, input):
        self.embedding_calls += 1
        return SimpleNamespace(data=[SimpleNamespace(embedding=[float(len(text))]) for text in input])

    def _create_chat(self, model, temperature, messages):
        self.last_messages = messages
        message = SimpleNamespace(content="  Staff get 25 days [1].  ")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def test_embedder_sends_batches_and_keeps_order():
    client = StubClient()
    texts = ["a" * (i + 1) for i in range(BATCH_SIZE + 5)]
    embeddings = Embedder(client, "model").embed_texts(texts)
    assert client.embedding_calls == 2
    assert embeddings[0] == [1.0] and embeddings[-1] == [float(BATCH_SIZE + 5)]


def test_generator_puts_numbered_context_in_prompt():
    client = StubClient()
    matches = [{"text": "Full-time staff get 25 days.", "metadata": {"source": "leave.md"}, "score": 0.9}]
    answer = Generator(client, "model").generate_answer("How much leave?", matches)
    assert answer == "Staff get 25 days [1]."
    user_message = client.last_messages[1]["content"]
    assert "[1] (from leave.md)" in user_message
    assert "Question: How much leave?" in user_message


def test_generator_without_matches_skips_the_api():
    client = StubClient()
    assert Generator(client, "model").generate_answer("q", []) == NO_CONTEXT_ANSWER
    assert client.last_messages is None
