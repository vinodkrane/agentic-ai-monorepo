"""A very small keyword retriever.

No embeddings and no vector database on purpose: it is free, fast and easy to test.
The point of this project is observability, not search quality.
"""
import re
from dataclasses import dataclass, replace
from pathlib import Path

from langsmith import traceable

WORD_RE = re.compile(r"[a-z0-9]+")

STOP_WORDS = {
    "a", "an", "and", "are", "can", "do", "does", "for", "from", "how", "i", "if", "in", "is",
    "it", "me", "my", "of", "on", "or", "the", "to", "what", "when", "where", "which", "who",
    "why", "will", "with", "you", "your", "there", "this", "that", "be", "get", "much", "many",
}


@dataclass
class Document:
    id: str
    title: str
    text: str
    score: int = 0


def tokenize(text):
    """Lowercase words without stop words. Returns a set, so repeated words count once."""
    return {word for word in WORD_RE.findall(text.lower()) if word not in STOP_WORDS}


def load_documents(folder):
    """Load every .md file in the folder. The file name (without .md) becomes the document id."""
    folder = Path(folder)
    if not folder.is_dir():
        raise FileNotFoundError(f"Docs folder not found: {folder}")

    documents = []
    for path in sorted(folder.glob("*.md")):
        text = path.read_text(encoding="utf-8").strip()
        first_line = text.splitlines()[0] if text else path.stem
        title = first_line.lstrip("# ").strip()
        documents.append(Document(id=path.stem, title=title, text=text))
    return documents


class KeywordRetriever:
    def __init__(self, documents, top_k=2, min_score=1):
        self.documents = documents
        self.top_k = top_k
        self.min_score = min_score
        self._doc_words = {doc.id: tokenize(doc.text) for doc in documents}

    @traceable(name="retrieve_documents", run_type="retriever")
    def search(self, query):
        query_words = tokenize(query)
        if not query_words:
            return []

        scored = []
        for doc in self.documents:
            score = len(query_words & self._doc_words[doc.id])
            if score >= self.min_score:
                scored.append(replace(doc, score=score))

        # highest score first; doc id breaks ties so results are always in the same order
        scored.sort(key=lambda d: (-d.score, d.id))
        return scored[: self.top_k]
