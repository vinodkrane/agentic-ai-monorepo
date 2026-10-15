"""Thin wrapper around the OpenAI client.

wrap_openai() is the important line: it makes LangSmith record every model call
with its prompt, answer, latency, token usage and cost.
"""
from dataclasses import dataclass

from langsmith.wrappers import wrap_openai
from openai import OpenAI, OpenAIError


class LLMError(Exception):
    """Calling the language model failed."""


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class OpenAIChatModel:
    def __init__(self, api_key, model="gpt-4o-mini", timeout=30):
        if not api_key:
            raise LLMError("OPENAI_API_KEY is not set. Add it to your .env file.")
        self.model = model
        self._client = wrap_openai(OpenAI(api_key=api_key, timeout=timeout, max_retries=2))

    def complete(self, system_prompt, user_prompt):
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except OpenAIError as exc:
            raise LLMError(f"OpenAI call failed: {exc}") from exc

        usage = response.usage
        return LLMResult(
            text=(response.choices[0].message.content or "").strip(),
            model=response.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
