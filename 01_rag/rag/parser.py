"""Step 1: read files and pull out plain text."""

import logging
from dataclasses import dataclass
from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


@dataclass
class Page:
    """A piece of text from a file. For PDFs this is one page; other files are one Page."""

    text: str
    source: str
    page_number: int | None = None


def parse_file(file_path: Path, source: str | None = None) -> list[Page]:
    """Read one file. `source` is the name saved with each chunk (defaults to the file name)."""
    source = source or file_path.name
    extension = file_path.suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {extension}")

    if extension in (".txt", ".md"):
        text = file_path.read_text(encoding="utf-8", errors="replace")
        pages = [Page(text=text, source=source)]
    elif extension == ".pdf":
        pages = _parse_pdf(file_path, source)
    else:
        pages = _parse_docx(file_path, source)

    # Drop pages with no real text (for example, scanned image pages).
    pages = [page for page in pages if page.text.strip()]
    if not pages:
        logger.warning("No text found in %s", source)
    return pages


def _parse_pdf(file_path: Path, source: str) -> list[Page]:
    reader = PdfReader(str(file_path))
    pages = []
    for index, pdf_page in enumerate(reader.pages, start=1):
        text = pdf_page.extract_text() or ""
        pages.append(Page(text=text, source=source, page_number=index))
    return pages


def _parse_docx(file_path: Path, source: str) -> list[Page]:
    document = DocxDocument(str(file_path))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    return [Page(text="\n\n".join(paragraphs), source=source)]


def find_files(folder: Path) -> list[Path]:
    """Return all supported files inside a folder (including sub-folders)."""
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    files = [
        path
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    return files
