"""
Structured logging via structlog.
Pretty console output in development, JSON in production.
Compatible with structlog 26.x.
"""
from __future__ import annotations

import logging
import sys

import structlog


SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "secret",
    "token",
    "api_key",
    "credential",
    "private_key",
    "authorization",
    "refresh_token",
    "access_token",
)


def scrub_sensitive_data(
    logger: logging.Logger, method_name: str, event_dict: dict
) -> dict:
    """Recursively scrub secrets and credentials from structured log events."""

    def _scrub(val: object, key: str = "") -> object:
        if isinstance(val, dict):
            return {k: _scrub(v, k) for k, v in val.items()}
        if isinstance(val, list):
            return [_scrub(item, key) for item in val]
        if isinstance(val, str) and key:
            k_lower = key.lower()
            if any(s in k_lower for s in SENSITIVE_KEY_SUBSTRINGS):
                # Don't redact safe keys like idempotency_key or preview_key if they are UUIDs
                if k_lower in ("idempotency_key", "preview_key", "sort_key"):
                    return val
                return "[REDACTED]"
        return val

    return {k: _scrub(v, k) for k, v in event_dict.items()}


def configure_logging(log_level: str = "INFO", production: bool = False) -> None:
    """
    Configure structlog. Call once at application startup.
    Compatible with structlog 24.x and 26.x.
    """
    # Use stdlib integration which properly supports .name attribute
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            scrub_sensitive_data,
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
