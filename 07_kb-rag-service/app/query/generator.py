import time

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage

from app import config
from app.query.prompts import SYSTEM_PROMPT, USER_TEMPLATE, format_context

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = ChatBedrockConverse(
            model=config.LLM_MODEL_ID,
            region_name=config.AWS_REGION,
            temperature=0,
            max_tokens=800,
        )
    return _llm


def build_messages(question, chunks):
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=USER_TEMPLATE.format(context=format_context(chunks), question=question)),
    ]


def generate(question, chunks):
    """Stream the answer so we can record TTFT and tokens/sec.

    Returns (answer, stats). stats has ttft_ms, gen_ms, output_tokens, tps.
    Note ttft here is from the LLM call only, not from the http request -
    retrieval time is tracked separately in the graph timings.
    """
    start = time.perf_counter()
    first_token_at = None
    parts = []
    output_tokens = 0

    for chunk in get_llm().stream(build_messages(question, chunks)):
        text = chunk.content if isinstance(chunk.content, str) else "".join(
            c.get("text", "") for c in chunk.content if isinstance(c, dict)
        )
        if text and first_token_at is None:
            first_token_at = time.perf_counter()
        parts.append(text)
        # bedrock sends usage on the last chunk
        if getattr(chunk, "usage_metadata", None):
            output_tokens = chunk.usage_metadata.get("output_tokens", output_tokens)

    end = time.perf_counter()
    answer = "".join(parts).strip()

    if not output_tokens:
        # rough fallback, ~4 chars per token
        output_tokens = max(1, len(answer) // 4)

    ttft = (first_token_at or end) - start
    decode_time = max(end - (first_token_at or start), 1e-6)
    stats = {
        "ttft_ms": int(ttft * 1000),
        "gen_ms": int((end - start) * 1000),
        "output_tokens": output_tokens,
        "tps": round(output_tokens / decode_time, 1),
    }
    return answer, stats
