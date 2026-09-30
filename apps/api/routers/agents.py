"""
Agent orchestration router — Phase 1.

Covers:
  - Triggering agent runs (enqueues ARQ job)
  - Reading agent run history (audit log)
  - Human approval gate (list + decide)

Phase 1 active agents: orchestrator only.
All other agents are registered but return "not_yet_implemented"
until their phase is approved.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from models import AgentRun, AgentRunStatus, ApprovalRequest, ApprovalStatus
from routers.auth import require_owner
from schemas import (
    AgentRunResponse,
    ApprovalDecision,
    ApprovalResponse,
    PaginatedResponse,
    TriggerAgentRequest,
)

router = APIRouter()
log = structlog.get_logger(__name__)

# Registry of agents and which phase they belong to.
# Phase 1: only "orchestrator" is active (returns real output).
# Others are registered so the API is future-proof, but clearly labelled.
AGENT_REGISTRY: dict[str, dict] = {
    "orchestrator":          {"phase": 1, "active": True},
    "lead_research":         {"phase": 2, "active": True},
    "outreach":              {"phase": 3, "active": False},
    "follow_up":             {"phase": 4, "active": False},
    "client_intelligence":   {"phase": 5, "active": False},
    "website_builder":       {"phase": 6, "active": False},
    "qa":                    {"phase": 7, "active": False},
    "deployment":            {"phase": 8, "active": False},
}


# ── Agent Runs ────────────────────────────────────────────────────────────────

@router.get("/runs", response_model=PaginatedResponse)
async def list_agent_runs(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    agent_name: Optional[str] = Query(None),
    run_status: Optional[AgentRunStatus] = Query(None, alias="status"),
    _owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """List agent runs. Requires authentication."""
    q = select(AgentRun)
    if agent_name:
        q = q.where(AgentRun.agent_name == agent_name)
    if run_status:
        q = q.where(AgentRun.status == run_status)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    runs = (
        await db.execute(
            q.order_by(AgentRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[AgentRunResponse.model_validate(r) for r in runs],
    )


@router.get("/runs/{run_id}", response_model=AgentRunResponse)
async def get_agent_run(
    run_id: uuid.UUID,
    _owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    """Get a single agent run by ID."""
    run = await db.get(AgentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return AgentRunResponse.model_validate(run)


@router.post("/trigger", response_model=AgentRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_agent(
    request: TriggerAgentRequest,
    _owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    """
    Trigger an agent run.

    Phase 1: only 'orchestrator' is active.
    Non-active agents are rejected with a 400 explaining which phase they belong to.

    If Redis is not running, the run record is created in the DB with
    status=PENDING but the job cannot be enqueued (reported in output_data).
    """
    info = AGENT_REGISTRY.get(request.agent_name)
    if info is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent '{request.agent_name}'. Available: {list(AGENT_REGISTRY)}",
        )
    if not info["active"]:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Agent '{request.agent_name}' is not active in Phase 1. "
                f"It will be implemented in Phase {info['phase']}."
            ),
        )

    # Create audit record
    run = AgentRun(
        agent_name=request.agent_name,
        status=AgentRunStatus.PENDING,
        input_data=request.input_data or {},
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()

    # Try to enqueue via ARQ
    enqueue_error: Optional[str] = None
    try:
        from arq import create_pool
        from core.redis import get_arq_redis_settings
        pool = await create_pool(get_arq_redis_settings())
        job = await pool.enqueue_job(
            f"run_{request.agent_name}_agent",
            str(run.id),
            request.input_data or {},
        )
        if job:
            run.job_id = job.job_id
        await pool.aclose()
        log.info("Agent job enqueued", agent=request.agent_name, run_id=str(run.id))
    except Exception as exc:
        enqueue_error = str(exc)
        run.status = AgentRunStatus.FAILED
        run.error_message = f"Could not enqueue job (is Redis running?): {enqueue_error[:200]}"
        run.completed_at = datetime.now(timezone.utc)
        log.warning(
            "Failed to enqueue agent job — Redis may not be running",
            agent=request.agent_name,
            error=enqueue_error[:100],
        )

    await db.flush()
    return AgentRunResponse.model_validate(run)


@router.get("/registry")
async def list_agent_registry() -> dict:
    """
    Return all registered agents with their phase and active status.
    No authentication required — informational endpoint.
    """
    return {
        "agents": AGENT_REGISTRY,
        "phase_1_active": [k for k, v in AGENT_REGISTRY.items() if v["active"]],
    }


# ── Approval Gate ─────────────────────────────────────────────────────────────

@router.get("/approvals", response_model=PaginatedResponse)
async def list_approvals(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    approval_status: Optional[ApprovalStatus] = Query(ApprovalStatus.PENDING, alias="status"),
    _owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """List approval requests. Defaults to pending only."""
    q = select(ApprovalRequest)
    if approval_status:
        q = q.where(ApprovalRequest.status == approval_status)

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(
            q.order_by(ApprovalRequest.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[ApprovalResponse.model_validate(r) for r in rows],
    )


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: uuid.UUID,
    decision: ApprovalDecision,
    owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> ApprovalResponse:
    """
    Owner approves or rejects a pending action.

    Once decided, the status cannot be changed again.
    The agent polling this record will detect the decision and proceed/abort.
    """
    approval = await db.get(ApprovalRequest, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status_code=400,
            detail=f"Approval already decided: {approval.status.value}",
        )

    approval.status = decision.decision
    approval.owner_note = decision.owner_note
    approval.reviewed_at = datetime.now(timezone.utc)
    await db.flush()

    log.info(
        "Approval decided",
        approval_id=str(approval_id),
        decision=decision.decision.value,
        owner=owner,
    )
    return ApprovalResponse.model_validate(approval)
