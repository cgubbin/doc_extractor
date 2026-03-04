"""Logging configuration for doc_extractor.

This module provides a thin wrapper around structlog for structured logging.
Logging is optional and can be disabled via environment variable.

Environment Variables:
    doc_extractor_LOG_LEVEL: Set log level (DEBUG, INFO, WARNING, ERROR)
                              Default: INFO
    doc_extractor_LOG_DISABLE: Set to "1" to disable all logging
                                Default: logging enabled

Usage:
    from doc_extractor.structured_logger import get_logger

    logger = get_logger(__name__)
    logger.info("parsing_started", pdf_path=str(pdf_path), pages=page_count)
    logger.debug("field_extracted", field="title", value=title)
"""

import logging
import os
import sys

import structlog


# Check if logging is disabled
_LOGGING_DISABLED = os.getenv("doc_extractor_LOG_DISABLE", "0") == "1"

# Get log level from environment
_LOG_LEVEL_STR = os.getenv("doc_extractor_LOG_LEVEL", "INFO").upper()
_LOG_LEVEL = getattr(logging, _LOG_LEVEL_STR, logging.INFO)


def _configure_structlog() -> None:
    """Configure structlog with sensible defaults for library usage.

    This also configures standard library logging to route through structlog,
    so messages from libraries like PIL, pymupdf, etc. will be captured.
    """
    if _LOGGING_DISABLED:
        # Configure minimal no-op logging
        structlog.configure(
            processors=[],
            wrapper_class=structlog.make_filtering_bound_logger(logging.CRITICAL + 1),
            context_class=dict,
            logger_factory=structlog.PrintLoggerFactory(file=open(os.devnull, "w")),
            cache_logger_on_first_use=True,
        )
        # Also disable stdlib logging
        logging.root.setLevel(logging.CRITICAL + 1)
        return

    # Shared processors for both structlog and stdlib
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.UnicodeDecoder(),
    ]

    # Configure structlog
    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging to use structlog formatting
    formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)
    handler.setLevel(_LOG_LEVEL)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(_LOG_LEVEL)


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
    global _LOG_LEVEL
    if _LOGGING_DISABLED:
        return

    _LOG_LEVEL = getattr(logging, level.upper(), logging.INFO)
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
