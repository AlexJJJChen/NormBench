"""Centralized logging setup for NormBench.

Provides:
  - a uniform log format
  - file logging with rotation
  - lightweight context binding (batch_id/sample_id/stage)
"""

from __future__ import annotations

import logging
import logging.config
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional

DEFAULT_EXTRA_KEYS = {
    "batch_id": "-",
    "sample_id": "-",
    "stage": "-",
}

DEFAULT_LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | %(stage)s | %(batch_id)s | %(sample_id)s | %(message)s"
)


class _ContextFilter(logging.Filter):
    """Ensure all log records contain the expected extra fields."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        for key, default in DEFAULT_EXTRA_KEYS.items():
            if not hasattr(record, key):
                setattr(record, key, default)
        if not hasattr(record, "stage"):
            record.stage = "-"
        return True


class ContextLoggerAdapter(logging.LoggerAdapter):
    """A LoggerAdapter that supports `.bind()` for adding context fields."""

    def bind(self, **extra: str) -> "ContextLoggerAdapter":
        merged = {**self.extra, **extra}
        return ContextLoggerAdapter(self.logger, merged)

    def process(self, msg, kwargs):  # noqa: D401
        extra = kwargs.setdefault("extra", {})
        if self.extra:
            extra = {**self.extra, **extra}
        kwargs["extra"] = extra
        return msg, kwargs


def setup_logging(
    log_dir: Path,
    *,
    level: str = "INFO",
    log_filename: str = "app.log",
    max_bytes: int = 5 * 1024 * 1024,
    backup_count: int = 5,
    console: bool = True,
) -> None:
    """Initialize global logging.

    Args:
        log_dir: Output directory for log files.
        level: Logging level (default: INFO).
        log_filename: Main log file name.
        max_bytes: Max size per log file before rotating.
        backup_count: Number of rotated log files to keep.
        console: Whether to also log to stderr.
    """

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / log_filename

    handlers: Dict[str, Dict[str, object]] = {
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": level,
            "formatter": "default",
            "filename": str(log_path),
            "maxBytes": max_bytes,
            "backupCount": backup_count,
            "encoding": "utf-8",
            "filters": ["context"],
        }
    }

    if console:
        handlers["console"] = {
            "class": "logging.StreamHandler",
            "level": level,
            "formatter": "default",
            "filters": ["context"],
        }

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "context": {
                "()": _ContextFilter,
            }
        },
        "formatters": {
            "default": {
                "format": DEFAULT_LOG_FORMAT,
            }
        },
        "handlers": handlers,
        "root": {
            "level": level,
            "handlers": list(handlers.keys()),
        },
    }

    logging.config.dictConfig(logging_config)


def get_logger(name: Optional[str] = None, **context: str) -> ContextLoggerAdapter:
    """Get a logger with context binding.

    Args:
        name: Logger name (default: root).
        context: Extra fields to bind to every log record.
    """

    base_logger = logging.getLogger(name)
    return ContextLoggerAdapter(base_logger, context)
