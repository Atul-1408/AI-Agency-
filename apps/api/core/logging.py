"""
Structured logging via structlog.
Pretty console output in development, JSON in production.
Compatible with structlog 26.x.
"""
from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(log_level: str = "INFO", production: bool = False) -> None:
    """
    Configure structlog. Call once at application startup.
    Compatible with structlog 24.x and 26.x.
    """
    # Use stdlib integration which properly supports .name attribute
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            (
                structlog.processors.JSONRenderer()
                if production
                else structlog.dev.ConsoleRenderer()
            ),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        level=logging.getLevelName(log_level.upper()),
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
    # Set level on root logger
    logging.getLogger().setLevel(logging.getLevelName(log_level.upper()))
