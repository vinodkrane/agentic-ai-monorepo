"""Structured JSON logging with Python's built-in logging module.

Every log line is one JSON object, so you can search logs with tools like
jq, PowerShell's ConvertFrom-Json, or any log platform.
"""
import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path

# Holds the id of the request we are handling right now.
# The formatter adds it to every line, so all logs for one request can be found together.
request_id_var = ContextVar("request_id", default="-")

# Attributes that every LogRecord has. Anything else came from `extra={...}`.
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}

SENSITIVE_KEYS = {"api_key", "openai_api_key", "langsmith_api_key", "password", "secret", "authorization"}

# OpenAI keys start with "sk-", LangSmith keys with "lsv2_".
_SECRET_PATTERN = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|lsv2_[A-Za-z0-9_]{8,})")


def new_request_id():
    return uuid.uuid4().hex[:12]


def mask_secrets(text):
    return _SECRET_PATTERN.sub("[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": mask_secrets(record.getMessage()),
            "request_id": request_id_var.get(),
        }

        # Copy fields passed with extra={...}, e.g. operation, status, duration_ms
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            if key.lower() in SENSITIVE_KEYS:
                value = "[REDACTED]"
            elif isinstance(value, str):
                value = mask_secrets(value)
            entry[key] = value

        if record.exc_info:
            exc_type, exc_value, _ = record.exc_info
            entry["exception"] = {
                "type": exc_type.__name__,
                "message": mask_secrets(str(exc_value)),
                "traceback": mask_secrets(self.formatException(record.exc_info)),
            }

        return json.dumps(entry, default=str, ensure_ascii=False)


def setup_logging(level="INFO", log_file=None):
    """Send JSON logs to stderr and (optionally) to a file. Safe to call more than once."""
    logger = logging.getLogger("app")
    logger.setLevel(level)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = JsonFormatter()

    # stderr, so the answer printed on stdout stays clean
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    logger.addHandler(console)

    if log_file:
        log_file = Path(log_file)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
