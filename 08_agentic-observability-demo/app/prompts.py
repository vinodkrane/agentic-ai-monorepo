"""Prompts live here so we can change them and compare versions in LangSmith experiments."""

SYSTEM_PROMPTS = {
    "v1": (
        "You are a helpful support assistant for StreamBox, a video streaming service. "
        "Answer the customer's question using the context below."
    ),
    "v2": (
        "You are a support assistant for StreamBox, a video streaming service. "
        "Answer ONLY using the context below. Keep the answer to 2-3 short sentences and "
        "keep exact numbers, prices and time limits from the context. "
        "If the context does not contain the answer, reply exactly: "
        "\"I don't know based on the help documents.\""
    ),
}

SMALL_TALK_PROMPT = (
    "You are a friendly support assistant for StreamBox, a video streaming service. "
    "Reply to greetings in one short sentence and offer to help with StreamBox questions."
)


def get_system_prompt(version):
    if version not in SYSTEM_PROMPTS:
        raise ValueError(f"Unknown prompt version '{version}'. Choose one of: {', '.join(SYSTEM_PROMPTS)}")
    return SYSTEM_PROMPTS[version]


def build_user_prompt(question, documents):
    context_parts = [f"[{doc.id}]\n{doc.text}" for doc in documents]
    context = "\n\n".join(context_parts)
    return f"Context:\n{context}\n\nQuestion: {question}"
