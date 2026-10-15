from app.ingest.chunker import make_chunks
from app.ingest.parser import clean, parse


def test_clean_joins_hyphen_breaks():
    assert clean("exam-\nple   text\n\n\n\nmore") == "example text\n\nmore"


def test_parse_txt():
    pages = parse("notes.txt", b"hello world\n\n\n\nbye")
    assert pages == [(1, "hello world\n\nbye")]


def test_parse_drops_empty():
    assert parse("empty.md", b"   \n\n ") == []


def test_chunks_have_ids_and_groups():
    text = "This is a sentence about annual leave. " * 100
    chunks = make_chunks("doc1", "leave.md", [(1, text)], ["all-staff"], chunk_size=300, overlap=50)

    assert len(chunks) > 1
    assert chunks[0]["chunk_id"] == "doc1-0000"
    assert chunks[1]["chunk_id"] == "doc1-0001"
    assert all(c["allowed_groups"] == ["all-staff"] for c in chunks)
    assert all(len(c["text"]) <= 300 for c in chunks)


def test_tiny_fragments_dropped():
    chunks = make_chunks("d", "s", [(1, "Page 3")], ["g"])
    assert chunks == []
