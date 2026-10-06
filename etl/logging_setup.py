"""Structured logging for the ETL. One call site, JSON on stdout."""
from __future__ import annotations

import logging
import sys

import structlog

_configured = False


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger. Safe to call from any module."""
    global _configured
    if not _configured:
        logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso", utc=True),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
        _configured = True
    return structlog.get_logger(name)
