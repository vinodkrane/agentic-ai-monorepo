import pytest

from app.validation import ValidationError, validate_question


def test_valid_question_is_returned_cleaned():
    assert validate_question("  How do I   reset\nmy password?  ") == "How do I reset my password?"


@pytest.mark.parametrize("bad_question", ["", "   ", "\n\t"])
def test_empty_question_is_rejected(bad_question):
    with pytest.raises(ValidationError, match="empty"):
        validate_question(bad_question)


@pytest.mark.parametrize("bad_question", [None, 123, ["a list"]])
def test_non_text_question_is_rejected(bad_question):
    with pytest.raises(ValidationError, match="text"):
        validate_question(bad_question)


def test_too_long_question_is_rejected():
    with pytest.raises(ValidationError, match="too long"):
        validate_question("a" * 501, max_chars=500)


def test_question_exactly_at_limit_is_allowed():
    assert len(validate_question("a" * 500, max_chars=500)) == 500
