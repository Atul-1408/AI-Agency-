"""
Redis connection management for the ARQ job queue.
"""
from __future__ import annotations

import urllib.parse
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from core.config import settings


def _parse_redis_url() -> dict:
    parsed = urllib.parse.urlparse(settings.REDIS_URL)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 6379,
        "db": int((parsed.path or "/0").lstrip("/") or 0),
    }


def get_arq_redis_settings():
    """
    Return arq-compatible RedisSettings from the REDIS_URL env var.
    Used by the ARQ worker at startup.
    """
    from arq.connections import RedisSettings
    parts = _parse_redis_url()
    return RedisSettings(
        host=parts["host"],
        port=parts["port"],
        database=parts["db"],
    )


# Shared async connection pool — do NOT use in workers (arq manages its own)
_pool: aioredis.ConnectionPool | None = None


def get_redis_pool() -> aioredis.ConnectionPool:
    global _pool
    if _pool is None:
        _pool = aioredis.ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=10,
            decode_responses=True,
        )
    return _pool


async def get_redis() -> AsyncGenerator[aioredis.Redis, None]:
    """FastAPI dependency: yields a Redis client, always closes it."""
    client = aioredis.Redis(connection_pool=get_redis_pool())
    try:
        yield client
    finally:
        await client.aclose()
