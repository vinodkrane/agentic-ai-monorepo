"""Step 2: split text into smaller chunks.

The approach:
1. Split the text into paragraphs (on blank lines).
2. If a paragraph is too long, split it into smaller pieces on word boundaries.
3. Join pieces together until a chunk is close to `chunk_size` characters.
4. Start each new chunk with the last `chunk_overlap` characters of the previous
   chunk, so an idea that crosses a chunk border is not lost.
"""

import re
from dataclasses import dataclass, field

from rag.parser import Page


@dataclass
class Chunk:
    text: str
    metadata: dict = field(default_factory=dict)


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []

    pieces = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= chunk_size:
            pieces.append(paragraph)
        else:
            pieces.extend(_split_long_paragraph(paragraph, chunk_size))

    chunks = []
    current = ""
    for piece in pieces:
        candidate = f"{current}\n\n{piece}" if current else piece
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        chunks.append(current)
        overlap = _tail(current, chunk_overlap)
        if overlap and len(overlap) + len(piece) + 1 <= chunk_size:
            current = f"{overlap} {piece}"
        else:
            current = piece

    if current:
        chunks.append(current)
    return chunks


def _split_long_paragraph(paragraph: str, chunk_size: int) -> list[str]:
    words = paragraph.split()
    pieces = []
    current = ""
    for word in words:
        # A single word longer than chunk_size (rare, e.g. a long URL) is cut hard.
        while len(word) > chunk_size:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(word[:chunk_size])
            word = word[chunk_size:]

        candidate = f"{current} {word}" if current else word
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


def _tail(text: str, length: int) -> str:
    """Return the last `length` characters, starting at a word boundary."""
    if length <= 0 or len(text) <= length:
        return text if length > 0 else ""
    tail = text[-length:]
    first_space = tail.find(" ")
    if first_space != -1:
        tail = tail[first_space + 1 :]
    return tail.strip()


def chunk_pages(pages: list[Page], chunk_size: int, chunk_overlap: int) -> list[Chunk]:
    chunks = []
    for page in pages:
        for text in split_text(page.text, chunk_size, chunk_overlap):
            metadata = {"source": page.source, "chunk_index": len(chunks)}
            if page.page_number is not None:
                metadata["page"] = page.page_number
            chunks.append(Chunk(text=text, metadata=metadata))
    return chunks
