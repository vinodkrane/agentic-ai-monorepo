"""Step 7: connect all the steps into one simple pipeline.

ingest:  file -> parse -> chunk -> embed -> store
ask:     question -> embed -> search -> generate answer
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from rag.chunker import chunk_pages
from rag.config import Settings
from rag.embedder import Embedder
from rag.generator import Generator, NO_CONTEXT_ANSWER, format_source
from rag.parser import find_files, parse_file
from rag.vector_store import VectorStore

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 2000


@dataclass
class Answer:
    text: str
    sources: list[dict]


class RAGPipeline:
    def __init__(
        self,
        settings: Settings,
        embedder: Embedder | None = None,
        generator: Generator | None = None,
        vector_store: VectorStore | None = None,
    ):
        self.settings = settings

        if embedder is None or generator is None:
            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is not set. Add it to your .env file.")
            client = OpenAI(api_key=settings.openai_api_key, max_retries=3, timeout=60)
            embedder = embedder or Embedder(client, settings.embedding_model)
            generator = generator or Generator(client, settings.chat_model)

        self.embedder = embedder
        self.generator = generator
        self.vector_store = vector_store or VectorStore(settings.db_path, settings.collection_name)

    # ---------- Ingestion ----------

    def ingest_file(self, file_path: Path, source: str | None = None) -> int:
        """Parse, chunk, embed and store one file. Returns the number of chunks stored."""
        source = source or file_path.name
        logger.info("Ingesting %s", source)

        pages = parse_file(file_path, source)
        chunks = chunk_pages(pages, self.settings.chunk_size, self.settings.chunk_overlap)
        if not chunks:
            logger.warning("Skipping %s: no text to store", source)
            return 0

        embeddings = self.embedder.embed_texts([chunk.text for chunk in chunks])
        self.vector_store.replace_source(source, chunks, embeddings)
        return len(chunks)

    def ingest_folder(self, folder: Path) -> dict:
        """Ingest every supported file in a folder. One bad file does not stop the rest."""
        files = find_files(folder)
        if not files:
            logger.warning("No supported files found in %s", folder)

        summary = {"files_ok": 0, "files_failed": 0, "chunks": 0}
        for file_path in files:
            # Use the path relative to the folder, so two files with the
            # same name in different sub-folders do not overwrite each other.
            source = str(file_path.relative_to(folder))
            try:
                summary["chunks"] += self.ingest_file(file_path, source)
                summary["files_ok"] += 1
            except Exception:
                logger.exception("Failed to ingest %s", source)
                summary["files_failed"] += 1

        logger.info(
            "Ingestion done: %d files ok, %d failed, %d chunks stored",
            summary["files_ok"], summary["files_failed"], summary["chunks"],
        )
        return summary

    # ---------- Question answering ----------

    def retrieve(self, question: str) -> list[dict]:
        query_embedding = self.embedder.embed_query(question)
        matches = self.vector_store.search(query_embedding, self.settings.top_k)
        relevant = [match for match in matches if match["score"] >= self.settings.min_relevance]
        logger.info("Found %d chunks, %d above relevance %.2f",
                    len(matches), len(relevant), self.settings.min_relevance)
        return relevant

    def ask(self, question: str) -> Answer:
        question = (question or "").strip()
        if not question:
            raise ValueError("Question cannot be empty")
        if len(question) > MAX_QUESTION_LENGTH:
            raise ValueError(f"Question is too long (max {MAX_QUESTION_LENGTH} characters)")

        if self.vector_store.count() == 0:
            return Answer(text="No documents have been ingested yet.", sources=[])

        matches = self.retrieve(question)
        if not matches:
            return Answer(text=NO_CONTEXT_ANSWER, sources=[])

        answer_text = self.generator.generate_answer(question, matches)
        sources = [
            {"number": number, "source": format_source(match["metadata"]), "score": round(match["score"], 3)}
            for number, match in enumerate(matches, start=1)
        ]
        return Answer(text=answer_text, sources=sources)
