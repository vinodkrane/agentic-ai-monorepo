"""Load settings from environment variables (and a .env file if present)."""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    embedding_model: str
    chat_model: str
    db_path: str
    collection_name: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    min_relevance: float
    log_level: str


def _get_int(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got '{value}'")


def _get_float(name: str, default: float) -> float:
    value = os.getenv(name, str(default))
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"{name} must be a number, got '{value}'")


def load_settings() -> Settings:
    load_dotenv()

    settings = Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        embedding_model=os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
        chat_model=os.getenv("CHAT_MODEL", "gpt-4o-mini"),
        db_path=os.getenv("DB_PATH", "./chroma_db"),
        collection_name=os.getenv("COLLECTION_NAME", "documents"),
        chunk_size=_get_int("CHUNK_SIZE", 1000),
        chunk_overlap=_get_int("CHUNK_OVERLAP", 150),
        top_k=_get_int("TOP_K", 4),
        min_relevance=_get_float("MIN_RELEVANCE", 0.2),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )

    if settings.chunk_size <= 0:
        raise ValueError("CHUNK_SIZE must be greater than 0")
    if not 0 <= settings.chunk_overlap < settings.chunk_size:
        raise ValueError("CHUNK_OVERLAP must be 0 or more and smaller than CHUNK_SIZE")
    if settings.top_k <= 0:
        raise ValueError("TOP_K must be greater than 0")

    return settings


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # These libraries are noisy at INFO level.
    for noisy in ("httpx", "openai", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
