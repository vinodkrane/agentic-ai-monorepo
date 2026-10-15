"""App settings. Everything comes from environment variables (a .env file is loaded if it exists)."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _to_bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _project_path(value):
    """Relative paths in .env are relative to the project folder, not to where you run the command."""
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    openai_model: str
    docs_dir: Path
    top_k: int
    max_question_chars: int
    prompt_version: str
    log_level: str
    log_file: Path
    log_questions: bool


def load_settings():
    # load_dotenv does not overwrite variables that are already set,
    # so real environment variables (and test settings) always win.
    load_dotenv(PROJECT_ROOT / ".env")

    return Settings(
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        docs_dir=_project_path(os.getenv("DOCS_DIR", "data/docs")),
        top_k=int(os.getenv("TOP_K", "2")),
        max_question_chars=int(os.getenv("MAX_QUESTION_CHARS", "500")),
        prompt_version=os.getenv("PROMPT_VERSION", "v1"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        log_file=_project_path(os.getenv("LOG_FILE", "logs/app.log")),
        log_questions=_to_bool(os.getenv("LOG_QUESTIONS"), default=False),
    )
