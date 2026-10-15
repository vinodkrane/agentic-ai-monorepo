"""Step 6: ask the LLM to answer the question using the retrieved chunks."""

import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You answer questions using only the context provided.
Rules:
- Use only facts from the context. Do not use outside knowledge.
- If the context does not contain the answer, say: "I could not find this in the documents."
- After each fact, add the source number in square brackets, like [1] or [2].
- Keep the answer short and clear."""

NO_CONTEXT_ANSWER = "I could not find this in the documents."


def build_context(matches: list[dict]) -> str:
    blocks = []
    for number, match in enumerate(matches, start=1):
        blocks.append(f"[{number}] (from {format_source(match['metadata'])})\n{match['text']}")
    return "\n\n---\n\n".join(blocks)


def format_source(metadata: dict) -> str:
    source = metadata.get("source", "unknown")
    if "page" in metadata:
        return f"{source}, page {metadata['page']}"
    return source


class Generator:
    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model = model

    def generate_answer(self, question: str, matches: list[dict]) -> str:
        if not matches:
            return NO_CONTEXT_ANSWER

        user_message = f"Context:\n\n{build_context(matches)}\n\nQuestion: {question}"
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        answer = response.choices[0].message.content or ""
        return answer.strip() or NO_CONTEXT_ANSWER
