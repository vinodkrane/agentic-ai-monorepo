import pytest

from rag.parser import find_files, parse_file
from tests.conftest import SAMPLE_DOCS


def test_parses_every_sample_format():
    for file_path in find_files(SAMPLE_DOCS):
        pages = parse_file(file_path)
        assert pages, f"no text from {file_path.name}"
        assert all(page.text.strip() for page in pages)


def test_pdf_keeps_page_numbers():
    pages = parse_file(SAMPLE_DOCS / "expenses_policy.pdf")
    assert [page.page_number for page in pages] == [1, 2]
    assert "35 pounds" in pages[1].text


def test_docx_text_is_extracted():
    pages = parse_file(SAMPLE_DOCS / "remote_working.docx")
    assert "VPN" in pages[0].text


def test_unsupported_file_type(tmp_path):
    bad_file = tmp_path / "data.csv"
    bad_file.write_text("a,b")
    with pytest.raises(ValueError):
        parse_file(bad_file)


def test_empty_file_returns_no_pages(tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_text("   \n\n ")
    assert parse_file(empty) == []


def test_missing_folder(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_files(tmp_path / "nope")
