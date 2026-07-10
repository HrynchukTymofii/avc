"""Structured logging: pretty console output for development, JSON lines for production.

Fields passed via ``log.info(..., extra={...})`` are appended to pretty output and
merged into the JSON payload, so call sites never need format-specific code.
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Literal

# Attributes present on every LogRecord; anything beyond these arrived via `extra=`.
# "message" and "asctime" are added by Formatter.format() itself, not by call sites.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({})).keys()) | {
    "taskName",
    "message",
    "asctime",
}


def _extra_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_extra_fields(record),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class PrettyFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = _extra_fields(record)
        if extras:
            base += " | " + " ".join(f"{k}={v}" for k, v in extras.items())
        return base


def setup_logging(fmt: Literal["pretty", "json"]) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            PrettyFormatter("%(asctime)s %(levelname)-8s %(name)s - %(message)s", "%H:%M:%S")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Route uvicorn's loggers through the root handler for one consistent format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
