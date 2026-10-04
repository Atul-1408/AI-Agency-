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

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import settings
from core.logging import configure_logging
from routers import agents, auth, conversations, follow_up, gmail, health, leads, outreach, prds, projects

# Configure logging before anything else
configure_logging(log_level=settings.LOG_LEVEL, production=settings.is_production)
log = structlog.get_logger(__name__)

VERSION = "0.1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    log.info(
        "AI Web Agency Agent API starting",
        version=VERSION,
        environment=settings.APP_ENV,
        nemotron_enabled=settings.NEMOTRON_ENABLED,
    )
    log.info(
        "Infrastructure: check /api/v1/health for database and Redis status"
    )
    yield
    log.info("API shutting down")


app = FastAPI(
    title="AI Web Agency Agent",
    description=(
        "Semi-autonomous AI system for lead research, outreach, website generation, "
        "QA, and deployment. The human owner remains in full control at all times.\n\n"
        "**Phase 1 — Foundation**"
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
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error(
        "Unhandled exception",
        path=str(request.url),
        method=request.method,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


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
