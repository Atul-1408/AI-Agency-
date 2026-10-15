"""
AI Web Agency Agent — FastAPI Backend
Phase 1 Foundation

Architecture:
  - Single owner (human-in-the-loop)
  - FastAPI + SQLAlchemy (async) + PostgreSQL
  - Redis + ARQ for job queue
  - Structured logging (structlog)
  - JWT authentication (FastAPI only — no NextAuth)

Phase 1 active endpoints:
  GET  /api/v1/health          — infrastructure health check
  POST /api/v1/auth/login      — owner login
  GET  /api/v1/auth/me         — validate token
  GET  /api/v1/agents/registry — list all agents + phase info
  GET  /api/v1/agents/runs     — agent run audit log (auth required)
  GET  /api/v1/agents/runs/{id}
  POST /api/v1/agents/trigger  — trigger an agent (auth required)
  GET  /api/v1/agents/approvals
  POST /api/v1/agents/approvals/{id}/decide
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.database import AsyncSessionLocal
from core.logging import configure_logging
from routers import (
    agent_workflow,
    agents,
    auth,
    conversations,
    follow_up,
    gmail,
    health,
    leads,
    outreach,
    prds,
    projects,
    website_builder,
    website_deployment,
    website_qa,
)

# Configure logging before anything else
configure_logging(log_level=settings.LOG_LEVEL, production=settings.is_production)
log = structlog.get_logger(__name__)

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown with configuration and readiness audit."""
    log.info(
        "AI Web Agency Agent API starting",
        version=VERSION,
        environment=settings.APP_ENV,
        nemotron_enabled=settings.NEMOTRON_ENABLED,
    )
    # Safe non-blocking readiness check on startup
    try:
        from services.system_readiness_service import SystemReadinessService
        async with AsyncSessionLocal() as session:
            readiness = await SystemReadinessService.get_full_readiness_report(session)
            log.info(
                "System startup configuration audit completed",
                overall_status=readiness["overall_status"],
                classifications=readiness["classifications_summary"],
            )
    except Exception as exc:
        log.warning("System startup readiness check skipped", error=str(exc)[:100])

    yield
    log.info("API shutting down")


app = FastAPI(
    title="AI Web Agency Agent",
    description=(
        "Semi-autonomous AI system for lead research, outreach, website generation, "
        "QA, and deployment. The human owner remains in full control at all times.\n\n"
        "**Phase 10 — Production Hardening & Real Integration Readiness**"
    ),
    version=VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Correlation-ID", "X-Request-ID"],
)


# ── Production Security Headers & Correlation ID Middleware ───────────────────
@app.middleware("http")
async def security_and_correlation_middleware(request: Request, call_next):
    """
    Enforces production security headers and binds unique correlation IDs
    to request context and structured logs for end-to-end observability.
    """
    correlation_id = (
        request.headers.get("X-Correlation-ID")
        or request.headers.get("X-Request-ID")
        or str(uuid.uuid4())
    )
    request.state.correlation_id = correlation_id
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

    response = await call_next(request)

    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
        "magnetometer=(), microphone=(), payment=(), usb=()"
    )
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    return response


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    log.error(
        "Unhandled exception",
        path=str(request.url),
        method=request.method,
        correlation_id=correlation_id,
        error=str(exc),
        exc_info=True,
    )
    content: dict[str, Any] = {
        "detail": "Internal server error",
        "correlation_id": correlation_id,
    }
    if not settings.is_production:
        content["type"] = type(exc).__name__
        content["debug_error"] = str(exc)[:200]

    return JSONResponse(status_code=500, content=content)


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health.router, prefix="/api/v1")
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(leads.router, prefix="/api/v1/leads", tags=["leads"])
app.include_router(outreach.router, prefix="/api/v1/outreach", tags=["outreach"])
app.include_router(gmail.router, prefix="/api/v1/gmail", tags=["gmail"])
app.include_router(follow_up.router, prefix="/api/v1/follow-ups", tags=["follow-ups"])
app.include_router(conversations.router, prefix="/api/v1/conversations", tags=["conversations"])
app.include_router(prds.router, prefix="/api/v1/prds", tags=["prds"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(website_builder.router, prefix="/api/v1", tags=["website-builder"])
app.include_router(website_qa.router, prefix="/api/v1", tags=["website-qa"])
app.include_router(website_deployment.router, prefix="/api/v1", tags=["website-deployment"])
app.include_router(agent_workflow.router, prefix="/api/v1")


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", tags=["root"])
async def root() -> dict:
    return {
        "name": "AI Web Agency Agent",
        "version": VERSION,
        "phase": 2,
        "phase_name": "Lead Research Agent",
        "environment": settings.APP_ENV,
        "docs": "/api/docs",
        "health": "/api/v1/health",
    }
