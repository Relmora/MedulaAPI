"""Structured logging: static messages plus explicitly allowed metadata."""

import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from json import dumps

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
SAFE_FIELDS = (
    "event",
    "method",
    "route",
    "status_code",
    "duration_ms",
    "error_code",
    "publisher_id",
    "worker_id",
    "message_id",
    "document_id",
    "job_id",
    "attempt_id",
    "claimed",
    "published",
    "failed",
    "lost_claims",
    "failure_count",
    "retry_seconds",
)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
        }
        for name in SAFE_FIELDS:
            if hasattr(record, name):
                entry[name] = getattr(record, name)
        if record.exc_info and record.exc_info[0]:
            # Exception messages/locals may include SQL parameters or credentials.
            entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "frames": [
                    {
                        "file": frame.filename,
                        "line": frame.lineno,
                        "function": frame.name,
                    }
                    for frame in traceback.extract_tb(record.exc_info[2])
                ],
            }
        return dumps(entry, ensure_ascii=True, default=str)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name if name.startswith("backend.") else f"backend.{name}")


def configure_logging(level: str = "INFO") -> None:
    logger = logging.getLogger("backend")

    for handler in list(logger.handlers):
        if getattr(handler, "_backend_json", False):
            logger.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(sys.stdout)
    handler._backend_json = True
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
