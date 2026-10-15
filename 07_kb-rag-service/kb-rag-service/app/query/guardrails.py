"""Cheap input/output checks.

These are regex + word list on purpose. They run on every request and need
to be fast. The heavier checks (deepeval toxicity/bias, LLM judge) run in
the eval suite, not on the hot path.
"""
import re

PII_PATTERNS = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "uk_phone": re.compile(r"(?:\+44\s?7\d{3}|\b07\d{3})\s?\d{3}\s?\d{3}\b"),
    "ni_number": re.compile(r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", re.I),
    "card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "postcode": re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b", re.I),
}

# kept short deliberately. if this grows, move it to a file or use
# Bedrock Guardrails instead (see docs/challenges...)
BLOCKLIST = {
    "kill yourself", "kys", "go die",
}


def find_pii(text):
    found = []
    for name, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            found.append(name)
    return found


def redact_pii(text):
    for name, pattern in PII_PATTERNS.items():
        text = pattern.sub(f"[{name.upper()}]", text)
    return text


def is_toxic(text):
    lower = text.lower()
    return any(term in lower for term in BLOCKLIST)
