"""Step 4 and 5: store chunks in ChromaDB and search them."""

import hashlib
import logging

import chromadb

from rag.chunker import Chunk

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, db_path: str, collection_name: str):
        self.client = chromadb.PersistentClient(path=db_path)
        # "cosine" makes the distance easy to turn into a 0-1 relevance score.
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def replace_source(self, source: str, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Remove old chunks for this source, then add the new ones.

        Doing a delete first means re-ingesting a changed file never leaves
        old, out-of-date chunks behind.
        """
        if len(chunks) != len(embeddings):
            raise ValueError("Number of chunks and embeddings must match")

        self.collection.delete(where={"source": source})
        if not chunks:
            return

        self.collection.add(
            ids=[_make_chunk_id(source, chunk) for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            embeddings=embeddings,
            metadatas=[chunk.metadata for chunk in chunks],
        )
        logger.info("Stored %d chunks for %s", len(chunks), source)

    def search(self, query_embedding: list[float], top_k: int) -> list[dict]:
        if self.count() == 0:
            return []

        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.count()),
            include=["documents", "metadatas", "distances"],
        )

        matches = []
        for text, metadata, distance in zip(
            result["documents"][0], result["metadatas"][0], result["distances"][0]
        ):
            matches.append({"text": text, "metadata": metadata, "score": 1 - distance})
        return matches

    def count(self) -> int:
        return self.collection.count()

    def list_sources(self) -> list[str]:
        records = self.collection.get(include=["metadatas"])
        return sorted({metadata["source"] for metadata in records["metadatas"]})


def _make_chunk_id(source: str, chunk: Chunk) -> str:
    # Same source + same position always gives the same id.
    key = f"{source}::{chunk.metadata['chunk_index']}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()
