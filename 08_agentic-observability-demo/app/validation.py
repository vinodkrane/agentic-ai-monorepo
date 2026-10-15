class ValidationError(ValueError):
    """The user's question is not usable."""


def validate_question(question, max_chars=500):
    """Return a cleaned question, or raise ValidationError."""
    if not isinstance(question, str):
        raise ValidationError("Question must be text.")

    # collapse tabs, new lines and repeated spaces into single spaces
    cleaned = " ".join(question.split())

    if not cleaned:
        raise ValidationError("Question cannot be empty.")

    if len(cleaned) > max_chars:
        raise ValidationError(f"Question is too long ({len(cleaned)} characters). The limit is {max_chars}.")

    return cleaned
