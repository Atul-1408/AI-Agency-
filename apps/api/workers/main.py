"""
ARQ Worker — Phase 1.

Runs as a separate process:
  .venv\Scripts\arq workers.main.WorkerSettings

Requires Redis to be running.

Phase 1 active jobs:
  run_orchestrator_agent — calls Orchestrator().run()

Future phases register new job functions here.
Non-active jobs are listed but return a clear "not implemented" response
rather than silently succeeding.
"""
from __future__ import annotations

import structlog

from core.config import settings
from core.logging import configure_logging
from core.redis import get_arq_redis_settings

configure_logging(log_level=settings.LOG_LEVEL, production=settings.is_production)
log = structlog.get_logger(__name__)


# ── Phase 1 Job Handlers ──────────────────────────────────────────────────────

async def run_orchestrator_agent(ctx: dict, run_id: str, input_data: dict) -> dict:
    """Phase 1: Active. Calls Orchestrator.run()."""
    from agents.orchestrator import Orchestrator
    return await Orchestrator().run(run_id, input_data)


# ── Future Phase Stubs (NOT active) ──────────────────────────────────────────
# These are registered so the job queue accepts calls without crashing,
# but they clearly report they are not implemented rather than silently
# returning empty data or fake success.

async def run_lead_research_agent(ctx: dict, run_id: str, input_data: dict) -> dict:
    """Phase 2: Active. Calls LeadResearchAgent.run()."""
    from agents.lead_research import LeadResearchAgent
    return await LeadResearchAgent().run(run_id, input_data)


async def run_outreach_agent(ctx: dict, run_id: str, input_data: dict) -> dict:
    """Phase 3: Not yet implemented."""
    return {"status": "not_implemented", "phase": 3}


async def run_follow_up_agent(ctx: dict, run_id: str, input_data: dict) -> dict:
    """Phase 4: Not yet implemented."""
    return {"status": "not_implemented", "phase": 4}


async def run_client_intelligence_agent(ctx: dict, run_id: str, input_data: dict) -> dict:
    """Phase 5: Not yet implemented."""
    return {"status": "not_implemented", "phase": 5}


async def run_website_builder_agent(ctx: dict, run_id: str, input_data: dict) -> dict:
    """Phase 6: Not yet implemented."""
    return {"status": "not_implemented", "phase": 6}


async def run_qa_agent(ctx: dict, run_id: str, input_data: dict) -> dict:
    """Phase 7: Not yet implemented."""
    return {"status": "not_implemented", "phase": 7}


async def run_deployment_agent(ctx: dict, run_id: str, input_data: dict) -> dict:
    """Phase 8: Not yet implemented."""
    return {"status": "not_implemented", "phase": 8}


# ── Lifecycle Hooks ───────────────────────────────────────────────────────────

async def startup(ctx: dict) -> None:
    log.info("ARQ Worker started", environment=settings.APP_ENV)


async def shutdown(ctx: dict) -> None:
    log.info("ARQ Worker shutting down")


# ── Worker Configuration ──────────────────────────────────────────────────────

class WorkerSettings:
    """
    ARQ worker settings.
    All job functions must be listed in `functions`.
    """
    functions = [
        run_orchestrator_agent,
        run_lead_research_agent,
        run_outreach_agent,
        run_follow_up_agent,
        run_client_intelligence_agent,
        run_website_builder_agent,
        run_qa_agent,
        run_deployment_agent,
    ]
    redis_settings = get_arq_redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 10
    job_timeout = 600       # 10 minutes max per job
    keep_result = 3600      # Keep results for 1 hour
    retry_jobs = True
    max_tries = 3
    poll_delay = 0.5        # Check for new jobs every 500ms
