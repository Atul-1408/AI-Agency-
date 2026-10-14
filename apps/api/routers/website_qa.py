"""
Website QA Router — Phase 7.

Provides authenticated, owner-scoped endpoints for:
- Initiating automated QA evaluations for a project
- Listing and inspecting QA runs and findings
- Automated AI repairs of detected defects via the Iterative Editing Engine

STRICT BOUNDARIES:
- Requires JWT owner authentication via require_owner.
- Enforces strict multi-tenant IDOR protection.
- Zero premature production deployment actions (Phase 8).
"""
from __future__ import annotations

from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from core.config import settings
from core.database import get_db
from models.website_qa import (
    QAFindingCategory,
    QAFindingSeverity,
    WebsiteQAFinding,
    WebsiteQARun,
    WebsiteQARunStatus,
)
from routers.auth import require_owner
from schemas.website_qa import (
    WebsiteQAFindingRepairRequest,
    WebsiteQAFindingRepairResponse,
    WebsiteQAFindingResponse,
    WebsiteQARunCreateRequest,
    WebsiteQARunDetailResponse,
    WebsiteQARunListResponse,
    WebsiteQARunResponse,
)
from services.website_qa_service import (
    QAConflictError,
    QAError,
    QAIneligibleError,
    QANotFoundError,
    QAOwnershipError,
    WebsiteQAService,
)

router = APIRouter()
log = structlog.get_logger(__name__)


def verify_owner_access(owner_email: str) -> None:
    """Verifies that the authenticated caller matches the configured agency owner."""
    if settings.OWNER_EMAIL and owner_email.lower().strip() != settings.OWNER_EMAIL.lower().strip():
        log.warning("Unauthorized owner access attempt on Website QA API", caller=owner_email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not authorized to access website QA resources.",
        )


@router.post(
    "/projects/{project_id}/qa-runs",
    response_model=WebsiteQARunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger an automated website QA evaluation run for a project",
)
async def create_qa_run(
    project_id: uuid.UUID,
    payload: Optional[WebsiteQARunCreateRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteQARunResponse:
    """Executes automated quality checks across build integrity, responsive design, a11y, and security."""
    verify_owner_access(owner_email)
    try:
        run = await WebsiteQAService.create_and_execute_qa_run(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
            request_payload=payload,
            created_by=owner_email,
        )
        return WebsiteQAService.serialize_qa_run(run)
    except QANotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except QAOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except QAIneligibleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except QAConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except QAError as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/projects/{project_id}/qa-runs",
    response_model=WebsiteQARunListResponse,
    summary="List all QA evaluation runs for a project",
)
async def list_qa_runs(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteQARunListResponse:
    """Returns chronological QA run history for a project."""
    verify_owner_access(owner_email)
    try:
        runs = await WebsiteQAService.list_qa_runs_for_project(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
        )
        return WebsiteQARunListResponse(
            items=[WebsiteQAService.serialize_qa_run(r) for r in runs],
            total=len(runs),
        )
    except QANotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except QAOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/qa-runs/{run_id}",
    response_model=WebsiteQARunDetailResponse,
    summary="Get detailed QA evaluation report with all findings",
)
async def get_qa_run_detail(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteQARunDetailResponse:
    """Returns detailed QA metrics, categorized findings, and deployment readiness."""
    verify_owner_access(owner_email)
    try:
        run = await WebsiteQAService.get_qa_run(db=db, run_id=run_id, owner_id=owner_email)

        # Fetch findings
        stmt = (
            select(WebsiteQAFinding)
            .where(WebsiteQAFinding.qa_run_id == run_id)
            .order_by(WebsiteQAFinding.created_at)
        )
        res = await db.execute(stmt)
        findings = list(res.scalars().all())

        severity_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = {}
        has_unresolved_critical = False

        for f in findings:
            sev_val = f.severity.value
            cat_val = f.category.value
            severity_counts[sev_val] = severity_counts.get(sev_val, 0) + 1
            category_counts[cat_val] = category_counts.get(cat_val, 0) + 1

            if not f.is_repaired and f.severity in (QAFindingSeverity.BLOCKER, QAFindingSeverity.HIGH):
                has_unresolved_critical = True

        can_deploy = not has_unresolved_critical and run.status in (
            WebsiteQARunStatus.PASSED,
            WebsiteQARunStatus.PASSED_WITH_WARNINGS,
        )

        return WebsiteQARunDetailResponse(
            run=WebsiteQAService.serialize_qa_run(run),
            findings=[WebsiteQAService.serialize_finding(f) for f in findings],
            summary_by_severity=severity_counts,
            summary_by_category=category_counts,
            can_deploy=can_deploy,
        )
    except QANotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except QAOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/qa-runs/{run_id}/findings",
    response_model=list[WebsiteQAFindingResponse],
    summary="List findings for a QA run with optional severity filter",
)
async def list_qa_findings(
    run_id: uuid.UUID,
    severity: Optional[QAFindingSeverity] = Query(None, description="Filter by finding severity"),
    category: Optional[QAFindingCategory] = Query(None, description="Filter by finding category"),
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> list[WebsiteQAFindingResponse]:
    """Lists findings for a run."""
    verify_owner_access(owner_email)
    run = await WebsiteQAService.get_qa_run(db=db, run_id=run_id, owner_id=owner_email)

    stmt = select(WebsiteQAFinding).where(WebsiteQAFinding.qa_run_id == run.id)
    if severity:
        stmt = stmt.where(WebsiteQAFinding.severity == severity)
    if category:
        stmt = stmt.where(WebsiteQAFinding.category == category)
    stmt = stmt.order_by(WebsiteQAFinding.created_at)

    res = await db.execute(stmt)
    findings = res.scalars().all()
    return [WebsiteQAService.serialize_finding(f) for f in findings]


@router.post(
    "/qa-findings/{finding_id}/repair",
    response_model=WebsiteQAFindingRepairResponse,
    summary="Trigger automated AI repair for a detected QA defect",
)
async def repair_qa_finding(
    finding_id: uuid.UUID,
    payload: Optional[WebsiteQAFindingRepairRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteQAFindingRepairResponse:
    """Applies a targeted source patch via the Iterative Editing Engine to resolve a QA defect."""
    verify_owner_access(owner_email)
    try:
        preview_id = payload.preview_id if payload else None
        res = await WebsiteQAService.repair_finding(
            db=db,
            finding_id=finding_id,
            owner_id=owner_email,
            preview_id=preview_id,
        )
        return res
    except QANotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except QAOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
