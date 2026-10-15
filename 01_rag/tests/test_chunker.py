from rag.chunker import chunk_pages, split_text
from rag.parser import Page


def test_short_text_is_one_chunk():
    assert split_text("Hello world.", 100, 10) == ["Hello world."]


def test_empty_text_gives_no_chunks():
    assert split_text("   ", 100, 10) == []


def test_chunks_respect_size_limit():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 40 for i in range(20))
    chunks = split_text(text, 300, 50)
    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)


def test_long_paragraph_is_split_on_words():
    text = "alpha " * 500
    chunks = split_text(text, 200, 0)
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert all("alph " not in chunk for chunk in chunks)  # no cut words


def test_overlap_repeats_end_of_previous_chunk():
    paragraphs = [f"Sentence number {i} is here." for i in range(30)]
    chunks = split_text("\n\n".join(paragraphs), 120, 40)
    for previous, current in zip(chunks, chunks[1:]):
        first_word_of_current = current.split()[0]
        assert first_word_of_current in previous


def test_no_text_is_lost():
    paragraphs = [f"Fact{i}" for i in range(200)]
    chunks = split_text("\n\n".join(paragraphs), 100, 0)
    joined = " ".join(chunks)
    assert all(word in joined for word in paragraphs)


def test_metadata_is_added():
    pages = [Page(text="Page one text.", source="a.pdf", page_number=1),
             Page(text="Page two text.", source="a.pdf", page_number=2)]
    chunks = chunk_pages(pages, 100, 10)
    assert [chunk.metadata for chunk in chunks] == [
        {"source": "a.pdf", "chunk_index": 0, "page": 1},
        {"source": "a.pdf", "chunk_index": 1, "page": 2},
    ]
