"""
Phase 9 REST Router for Central Agent Workflow Orchestration.
"""
from __future__ import annotations

import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import get_db
from models.agent_workflow import AgentWorkflow, WorkflowStepRecord
from routers.auth import require_owner
from schemas.agent_workflow import (
    ProviderConnectivityResponse,
    WorkflowAdvanceRequest,
    WorkflowApprovalActionRequest,
    WorkflowCreateRequest,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowStepRecordResponse,
)
from services.workflow_orchestrator_service import (
    WorkflowError,
    WorkflowGateRequiredError,
    WorkflowInvalidStateError,
    WorkflowNotFoundError,
    WorkflowOrchestratorService,
    WorkflowOwnershipError,
)

router = APIRouter(prefix="/workflows", tags=["Workflows"])
log = structlog.get_logger(__name__)


def _model_to_response(wf: AgentWorkflow) -> WorkflowResponse:
    """Helper to convert ORM model to Pydantic response."""
    step_records = [
        WorkflowStepRecordResponse.model_validate(r) for r in (wf.step_records or [])
    ]
    resp = WorkflowResponse.model_validate(wf)
    resp.step_records = step_records
    return resp


async def _to_workflow_response(db: AsyncSession, wf: AgentWorkflow) -> WorkflowResponse:
    """Helper to convert ORM model to Pydantic response with fresh committed state."""
    await db.commit()
    steps_stmt = (
        select(WorkflowStepRecord)
        .where(WorkflowStepRecord.workflow_id == wf.id)
        .order_by(WorkflowStepRecord.created_at.asc())
    )
    step_rows = (await db.execute(steps_stmt)).scalars().all()

    wf_stmt = select(AgentWorkflow).where(AgentWorkflow.id == wf.id)
    fresh_wf = (await db.execute(wf_stmt)).scalar_one()

    resp = WorkflowResponse.model_validate(fresh_wf)
    resp.step_records = [
        WorkflowStepRecordResponse.model_validate(r) for r in step_rows
    ]
    return resp


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreateRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Create a new end-to-end multi-agent workflow."""
    try:
        wf = await WorkflowOrchestratorService.create_workflow(
            db=db,
            owner_id=owner_email,
            title=payload.title,
            description=payload.description,
            mode=payload.mode,
            is_dry_run=payload.is_dry_run,
            idempotency_key=payload.idempotency_key,
            initial_data=payload.initial_data,
        )
        return await _to_workflow_response(db, wf)
    except Exception as exc:
        log.exception("create_workflow_failed", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WorkflowListResponse:
    """List workflows owned by the authenticated caller."""
    items, total = await WorkflowOrchestratorService.list_workflows(
        db=db,
        owner_id=owner_email,
        page=page,
        page_size=page_size,
        status_filter=status_filter,
    )
    return WorkflowListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_model_to_response(wf) for wf in items],
    )


@router.get("/connectivity", response_model=ProviderConnectivityResponse)
async def get_provider_connectivity(
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> ProviderConnectivityResponse:
    """Inspect status of external providers (Database, Redis, AI, Gmail, GitHub, Vercel)."""
    data = await WorkflowOrchestratorService.inspect_provider_connectivity(db)
    return ProviderConnectivityResponse.model_validate(data)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Fetch a single workflow by ID with full step records."""
    try:
        wf = await WorkflowOrchestratorService.get_workflow(db, workflow_id, owner_email)
        return _model_to_response(wf)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except WorkflowOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post("/{workflow_id}/advance", response_model=WorkflowResponse)
async def advance_workflow(
    workflow_id: uuid.UUID,
    payload: Optional[WorkflowAdvanceRequest] = None,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Advance workflow progression or retry from current state."""
    try:
        overrides = payload.input_overrides if payload else None
        wf = await WorkflowOrchestratorService.run_or_advance_workflow(
            db=db,
            workflow_id=workflow_id,
            owner_id=owner_email,
            input_overrides=overrides,
        )
        return await _to_workflow_response(db, wf)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except WorkflowOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except WorkflowInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except WorkflowGateRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except Exception as exc:
        log.exception("advance_workflow_failed", workflow_id=str(workflow_id), error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post("/{workflow_id}/approve", response_model=WorkflowResponse)
async def approve_workflow_gate(
    workflow_id: uuid.UUID,
    payload: WorkflowApprovalActionRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Submit Human Owner Approval or Rejection for the paused gate."""
    try:
        wf = await WorkflowOrchestratorService.handle_approval_action(
            db=db,
            workflow_id=workflow_id,
            owner_id=owner_email,
            decision=payload.decision,
            notes=payload.notes,
        )
        return await _to_workflow_response(db, wf)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except WorkflowOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except WorkflowInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{workflow_id}/retry", response_model=WorkflowResponse)
async def retry_workflow_stage(
    workflow_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Safely retry a failed stage if allowed by safety policies."""
    try:
        wf = await WorkflowOrchestratorService.retry_failed_stage(
            db=db,
            workflow_id=workflow_id,
            owner_id=owner_email,
        )
        return await _to_workflow_response(db, wf)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except WorkflowOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except WorkflowInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{workflow_id}/cancel", response_model=WorkflowResponse)
async def cancel_workflow(
    workflow_id: uuid.UUID,
    reason: Optional[str] = Query(None),
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    """Cancel an active or paused workflow."""
    try:
        wf = await WorkflowOrchestratorService.cancel_workflow(
            db=db,
            workflow_id=workflow_id,
            owner_id=owner_email,
            reason=reason,
        )
        return await _to_workflow_response(db, wf)
    except WorkflowNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except WorkflowOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except WorkflowInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
