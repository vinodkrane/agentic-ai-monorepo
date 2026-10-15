import pytest

from app.retriever import KeywordRetriever, load_documents, tokenize


def test_all_sample_documents_are_loaded(documents):
    ids = [doc.id for doc in documents]
    assert ids == ["downloads", "password-reset", "refund-policy", "subscription-plans", "supported-devices"]
    assert documents[2].title == "Refund policy"


def test_missing_docs_folder_raises_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_documents(tmp_path / "does-not-exist")


def test_tokenize_removes_stop_words_and_case():
    assert tokenize("How do I get a REFUND?") == {"refund"}


@pytest.mark.parametrize(
    "question, expected_doc",
    [
        ("How many days do I have to ask for a refund?", "refund-policy"),
        ("How much does the Premium plan cost?", "subscription-plans"),
        ("How long is the password reset link valid?", "password-reset"),
        ("How many devices can I sign in on with one account?", "supported-devices"),
        ("How long do downloads stay on my device?", "downloads"),
    ],
)
def test_best_document_is_ranked_first(retriever, question, expected_doc):
    results = retriever.search(question)
    assert results, "expected at least one document"
    assert results[0].id == expected_doc


def test_unrelated_question_returns_nothing(retriever):
    assert retriever.search("What is the capital of France?") == []


def test_top_k_limits_number_of_results(documents):
    retriever = KeywordRetriever(documents, top_k=1)
    assert len(retriever.search("plan refund password downloads devices")) == 1


def test_results_have_scores(retriever):
    results = retriever.search("refund gift card")
    assert results[0].score >= 1
