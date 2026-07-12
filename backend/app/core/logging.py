"""Application-wide logging configuration.

Provides console and rotating-file handlers, a structured JSON log
format, environment-aware log levels, and request-ID correlation so
every log line can be traced back to the request that produced it.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from app.core.config import get_settings

_request_id_ctx: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


def set_request_id(request_id: Optional[str]) -> None:
    """Bind the current request's correlation ID for the active execution context.

    Args:
        request_id: The ID to bind, or ``None`` to clear it.
    """
    _request_id_ctx.set(request_id)


def get_request_id() -> Optional[str]:
    """Return the request ID bound to the current execution context, if any.

    Returns:
        The bound request ID, or ``None`` outside of a request.
    """
    return _request_id_ctx.get()


class RequestIDFilter(logging.Filter):
    """Injects the current request ID into every log record it processes."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class JSONFormatter(logging.Formatter):
    """Renders log records as single-line JSON for structured log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


_TEXT_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | request_id=%(request_id)s | %(message)s"

# Third-party client libraries emit very verbose DEBUG-level wire logs
# (every socket read/write). Development mode wants DEBUG for CodeSage's
# own loggers, not a firehose from every dependency, so these are always
# capped at WARNING regardless of the resolved application log level.
_NOISY_THIRD_PARTY_LOGGERS = ("httpcore", "httpx", "asyncio", "qdrant_client")


def configure_logging() -> None:
    """Configure console and (optionally) rotating-file logging for the process.

    Reads :class:`~app.core.config.LoggingSettings` to decide the level,
    format, and destinations. Idempotent: clears any previously attached
    handlers so repeated calls (e.g. under a dev auto-reloader) never
    duplicate log lines.
    """
    settings = get_settings()
    level = settings.logging.resolved_level(settings.app.environment, settings.app.debug)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    formatter: logging.Formatter
    formatter = JSONFormatter() if settings.logging.log_format == "json" else logging.Formatter(_TEXT_FORMAT)

    request_id_filter = RequestIDFilter()

    if settings.logging.log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(request_id_filter)
        root_logger.addHandler(console_handler)

    if settings.logging.log_to_file:
        log_dir = Path(settings.logging.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / settings.logging.log_file_name,
            maxBytes=settings.logging.log_max_bytes,
            backupCount=settings.logging.log_backup_count,
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(request_id_filter)
        root_logger.addHandler(file_handler)

    for noisy_logger in _NOISY_THIRD_PARTY_LOGGERS:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def get_logger(name: str = "codesage") -> logging.Logger:
    """FastAPI-injectable dependency returning a named logger.

    Args:
        name: Logger name, conventionally the owning module's dotted path.

    Returns:
        A standard library :class:`logging.Logger` configured by
        :func:`configure_logging`.
    """
    return logging.getLogger(name)
