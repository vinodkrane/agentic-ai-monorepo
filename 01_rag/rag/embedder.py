"""Step 3: turn text into vectors (embeddings) using the OpenAI API."""

import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

# The API accepts many texts per request. Sending them in batches is much
# faster than one request per chunk, and keeps each request a safe size.
BATCH_SIZE = 100


class Embedder:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            logger.debug("Embedding batch of %d texts", len(batch))
            response = self.client.embeddings.create(model=self.model, input=batch)
            embeddings.extend(item.embedding for item in response.data)
        return embeddings

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]
