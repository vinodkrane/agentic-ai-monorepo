SYSTEM_PROMPT = """You answer questions for staff using internal documents.

Rules:
- Use only the context below. If the answer is not in the context, say
  "I couldn't find that in the documents you have access to."
- Cite the sources you used with their number, like [1] or [2].
- Keep it short. Bullet points are fine for lists.
- Never repeat personal data (emails, phone numbers, NI numbers) even if
  it appears in the context.
"""

USER_TEMPLATE = """Context:
{context}

Question: {question}"""

NO_ANSWER = "I couldn't find that in the documents you have access to."
BLOCKED_ANSWER = "Sorry, I can't help with that request."


def format_context(chunks):
    lines = []
    for i, c in enumerate(chunks, start=1):
        lines.append(f"[{i}] (source: {c['source']}, page {c.get('page', '?')})\n{c['text']}")
    return "\n\n".join(lines)
