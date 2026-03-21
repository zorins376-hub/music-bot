"""
Structured logging configuration using structlog.

In production (LOG_FORMAT=json), outputs JSON for log aggregation.
In development (LOG_FORMAT=console), outputs pretty colored logs.
"""
import logging
import os
import sys
from typing import Any

import structlog
from structlog.types import Processor

# Determine environment
LOG_FORMAT = os.getenv("LOG_FORMAT", "console").lower()
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
IS_JSON = LOG_FORMAT == "json"


def add_app_context(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Add application-level context to all log entries."""
    event_dict.setdefault("app", "music-bot")
    return event_dict


def configure_logging() -> None:
    """
    Configure structlog for the application.
    
    Call this once at application startup (in main.py / webapp entry).
    """
    # Shared processors for both structlog and stdlib integration
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
        add_app_context,
    ]

    if IS_JSON:
        final_processor = structlog.processors.JSONRenderer()
    else:
        final_processor = structlog.dev.ConsoleRenderer(colors=True)

    # Configure structlog: render via stdlib so both structlog and
    # standard-library loggers go through the same pipeline.
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # ProcessorFormatter bridges stdlib → structlog rendering
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            final_processor,
        ],
        foreign_pre_chain=shared_processors,
    )

    # Configure standard library logging to use structlog formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Remove existing handlers and set our handler
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Suppress noisy third-party loggers
    for name in ("httpcore", "httpx", "aiohttp.access", "asyncio"):
        logging.getLogger(name).setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog logger instance.
    
    Usage:
        from bot.logging_config import get_logger
        logger = get_logger(__name__)
        logger.info("event_name", user_id=123, action="play")
    """
    return structlog.get_logger(name)


# Convenience: configure on import if this module is imported
# (can be disabled by setting STRUCTLOG_LAZY_INIT=1)
if not os.getenv("STRUCTLOG_LAZY_INIT"):
    configure_logging()
