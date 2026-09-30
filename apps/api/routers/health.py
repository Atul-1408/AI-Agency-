"""
Health check endpoint.

Reports the real status of all infrastructure dependencies.
Never returns a false positive — if the database is not reachable,
the response says so clearly.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter

from core.config import settings
from core.database import AsyncSessionLocal
from schemas import HealthResponse, ServiceStatus

router = APIRouter()
log = structlog.get_logger(__name__)

VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """
    System health check.

    Returns the real connectivity status of:
    - PostgreSQL database
    - Redis

    Status values:
      "ok"          — reachable and responsive
      "unavailable" — not configured or not running (expected in local dev)
      "error"       — configured but encountered an unexpected error
    """
    services: dict[str, ServiceStatus] = {}
    overall = "ok"

    # ── Database check ────────────────────────────────────────
    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        services["database"] = ServiceStatus(status="ok")
    except Exception as exc:
        detail = str(exc)
        if "No module named 'asyncpg'" in detail:
            services["database"] = ServiceStatus(
                status="unavailable",
                detail="asyncpg not installed (requires MSVC Build Tools). See QUICKSTART.md.",
            )
        elif "Connection refused" in detail or "could not connect" in detail.lower() or "asyncpg" in detail:
            services["database"] = ServiceStatus(
                status="unavailable",
                detail="PostgreSQL is not running. See QUICKSTART.md.",
            )
        else:
            services["database"] = ServiceStatus(status="error", detail=detail[:200])
        overall = "degraded"
        log.warning("Database health check failed", error=detail[:100])

    # ── Redis check ───────────────────────────────────────────
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        services["redis"] = ServiceStatus(status="ok")
    except Exception as exc:
        detail = str(exc)
        if "Connection refused" in detail or "Cannot connect" in detail.lower() or "Timeout" in detail or "timeout" in detail.lower():
            services["redis"] = ServiceStatus(
                status="unavailable",
                detail="Redis is not running. See QUICKSTART.md.",
            )
        else:
            services["redis"] = ServiceStatus(status="error", detail=detail[:200])
        overall = "degraded"
        log.warning("Redis health check failed", error=detail[:100])

    return HealthResponse(
        status=overall,
        version=VERSION,
        environment=settings.APP_ENV,
        services=services,
    )
