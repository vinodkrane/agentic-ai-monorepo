import pytest

from rag.pipeline import RAGPipeline
from tests.conftest import SAMPLE_DOCS, FakeEmbedder, FakeGenerator


@pytest.fixture
def pipeline(settings):
    return RAGPipeline(settings, embedder=FakeEmbedder(), generator=FakeGenerator())


def test_ingest_and_ask(pipeline):
    summary = pipeline.ingest_folder(SAMPLE_DOCS)
    assert summary["files_ok"] == 4
    assert summary["files_failed"] == 0
    assert pipeline.vector_store.count() == summary["chunks"]

    answer = pipeline.ask("lost laptop report to IT Service Desk")
    assert answer.text == "answer based on 3 chunks"
    assert "it_security.txt" in [source["source"] for source in answer.sources]


def test_pdf_sources_show_page(pipeline):
    pipeline.ingest_folder(SAMPLE_DOCS)
    answer = pipeline.ask("How much can I claim for meals per day when travelling overnight?")
    assert answer.sources[0]["source"] == "expenses_policy.pdf, page 2"


def test_reingest_does_not_duplicate(pipeline):
    first = pipeline.ingest_folder(SAMPLE_DOCS)
    pipeline.ingest_folder(SAMPLE_DOCS)
    assert pipeline.vector_store.count() == first["chunks"]


def test_reingest_removes_old_chunks(pipeline, tmp_path):
    doc = tmp_path / "notes.txt"
    doc.write_text("\n\n".join(f"Old paragraph {i} " + "text " * 50 for i in range(10)))
    pipeline.ingest_file(doc)
    doc.write_text("Just one short line now.")
    pipeline.ingest_file(doc)
    assert pipeline.vector_store.count() == 1


def test_bad_file_does_not_stop_ingestion(pipeline, tmp_path):
    (tmp_path / "good.txt").write_text("Good document about holidays.")
    (tmp_path / "broken.pdf").write_text("this is not really a pdf")
    summary = pipeline.ingest_folder(tmp_path)
    assert summary == {"files_ok": 1, "files_failed": 1, "chunks": 1}


def test_ask_before_ingest(pipeline):
    assert pipeline.ask("anything?").text == "No documents have been ingested yet."


def test_empty_question_is_rejected(pipeline):
    with pytest.raises(ValueError):
        pipeline.ask("   ")


def test_unrelated_question_finds_nothing(pipeline, settings):
    pipeline.settings = settings.__class__(**{**settings.__dict__, "min_relevance": 0.5})
    pipeline.ingest_folder(SAMPLE_DOCS)
    answer = pipeline.ask("zebra quantum volcano")
    assert answer.sources == []
    assert "could not find" in answer.text


def test_missing_api_key_gives_clear_error(settings):
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        RAGPipeline(settings)
