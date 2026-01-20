"""Logging configuration for patent_ingest.

This module provides a thin wrapper around structlog for structured logging.
Logging is optional and can be disabled via environment variable.

Environment Variables:
    PATENT_INGEST_LOG_LEVEL: Set log level (DEBUG, INFO, WARNING, ERROR)
                              Default: INFO
    PATENT_INGEST_LOG_DISABLE: Set to "1" to disable all logging
                                Default: logging enabled

Usage:
    from patent_ingest.logging import get_logger

    logger = get_logger(__name__)
    logger.info("parsing_started", pdf_path=str(pdf_path), pages=page_count)
    logger.debug("field_extracted", field="title", value=title)
"""

import logging
import os
import sys
from typing import Any

import structlog


# Check if logging is disabled
_LOGGING_DISABLED = os.getenv("PATENT_INGEST_LOG_DISABLE", "0") == "1"

# Get log level from environment
_LOG_LEVEL_STR = os.getenv("PATENT_INGEST_LOG_LEVEL", "INFO").upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_STR, logging.INFO)


def _configure_structlog() -> None:
    """Configure structlog with sensible defaults for library usage."""
    if _LOGGING_DISABLED:
        # Configure minimal no-op logging
        structlog.configure(
            processors=[],
            wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL + 1),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(file=open(os.devnull, 'w')),
            cache_logger_on_first_use=True,
        )
        return

    # Configure structured JSON logging
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_LOG_LEVEL),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


# Configure on module import
_configure_structlog()


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a configured logger instance.

    Args:
        name: Logger name (typically __name__ of the calling module)

    Returns:
        Configured structlog logger instance

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("operation_complete", items=42, duration_ms=1234)
    """
    return structlog.get_logger(name)


def set_log_level(level: str) -> None:
    """Dynamically change log level.

    Args:
        level: Log level string (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    if _LOGGING_DISABLED:
        return

    log_level = getattr(logging, level.upper(), logging.INFO)
    _configure_structlog()


def disable_logging() -> None:
    """Completely disable logging output."""
    global _LOGGING_DISABLED
    _LOGGING_DISABLED = True
    _configure_structlog()


def enable_logging(level: str = "INFO") -> None:
    """Re-enable logging after it was disabled.

    Args:
        level: Log level to set (DEBUG, INFO, WARNING, ERROR)
    """
    global _LOGGING_DISABLED, _LOG_LEVEL
    _LOGGING_DISABLED = False
    _LOG_LEVEL = getattr(logging, level.upper(), logging.INFO)
    _configure_structlog()


# Convenience re-exports for common use
__all__ = [
    "get_logger",
    "set_log_level",
    "disable_logging",
    "enable_logging",
]
