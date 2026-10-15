"""
Website Deployment Router — Phase 8.

Provides authenticated, owner-scoped endpoints for:
- Pre-deployment eligibility verification (checking QA passing status and zero blockers)
- Deployment request initiation & Gate 5 owner approval binding
- Deployment pipeline execution (GitHub repo publish & Vercel deployment)
- Safe cancellation
- Custom domain binding and DNS/SSL verification
"""
from __future__ import annotations

from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from core.config import settings
from core.database import get_db
from routers.auth import require_owner
from schemas.website_deployment import (
    WebsiteDeploymentApproveRequest,
    WebsiteDeploymentCancelRequest,
    WebsiteDeploymentCreateRequest,
    WebsiteDeploymentDomainRequest,
    WebsiteDeploymentEligibilityResponse,
    WebsiteDeploymentExecuteRequest,
    WebsiteDeploymentResponse,
)
from services.website_deployment_service import (
    DeploymentApprovalRequiredError,
    DeploymentConflictError,
    DeploymentEligibilityError,
    DeploymentError,
    DeploymentInvalidStateError,
    DeploymentNotFoundError,
    DeploymentOwnershipError,
    WebsiteDeploymentService,
)

router = APIRouter()
log = structlog.get_logger(__name__)


def verify_owner_access(owner_email: str) -> None:
    """Verifies that the authenticated caller matches the configured agency owner."""
    if settings.OWNER_EMAIL and owner_email.lower().strip() != settings.OWNER_EMAIL.lower().strip():
        log.warning("Unauthorized owner access attempt on Deployment API", caller=owner_email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: caller is not the authorized agency owner.",
        )


# ── Eligibility Verification ──────────────────────────────────────────────────

@router.get(
    "/projects/{project_id}/deployments/eligibility",
    response_model=WebsiteDeploymentEligibilityResponse,
    summary="Check deployment eligibility for a project",
)
async def check_deployment_eligibility(
    project_id: uuid.UUID,
    target_version: Optional[int] = Query(None, description="Optional target version"),
    code_generation_id: Optional[uuid.UUID] = Query(None, description="Optional code generation ID"),
    qa_run_id: Optional[uuid.UUID] = Query(None, description="Optional QA run ID"),
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WebsiteDeploymentEligibilityResponse:
    verify_owner_access(owner_email)
    try:
        return await WebsiteDeploymentService.check_eligibility(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
            target_version=target_version,
            code_generation_id=code_generation_id,
            qa_run_id=qa_run_id,
        )
    except DeploymentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except Exception as exc:
        log.exception("check_deployment_eligibility_failed", project_id=str(project_id))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ── Deployments Lifecycle ─────────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/deployments/request",
    response_model=WebsiteDeploymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a new deployment (initiates Gate 5 approval for production)",
)
async def request_deployment(
    project_id: uuid.UUID,
    payload: WebsiteDeploymentCreateRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WebsiteDeploymentResponse:
    verify_owner_access(owner_email)
    try:
        deployment = await WebsiteDeploymentService.request_deployment(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
            request_payload=payload,
        )
        await db.commit()
        await db.refresh(deployment)
        return WebsiteDeploymentResponse.model_validate(deployment)
    except DeploymentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except DeploymentEligibilityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Project is not eligible for deployment", "reasons": exc.reasons},
        )
    except DeploymentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except DeploymentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        log.exception("request_deployment_failed", project_id=str(project_id))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get(
    "/projects/{project_id}/deployments",
    response_model=List[WebsiteDeploymentResponse],
    summary="List all deployments for a project",
)
async def list_deployments_for_project(
    project_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> List[WebsiteDeploymentResponse]:
    verify_owner_access(owner_email)
    try:
        deployments = await WebsiteDeploymentService.list_deployments_for_project(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
        )
        return [WebsiteDeploymentResponse.model_validate(d) for d in deployments]
    except DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DeploymentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get(
    "/deployments/{deployment_id}",
    response_model=WebsiteDeploymentResponse,
    summary="Get details of a deployment",
)
async def get_deployment(
    deployment_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WebsiteDeploymentResponse:
    verify_owner_access(owner_email)
    try:
        dep = await WebsiteDeploymentService.get_deployment(db, deployment_id, owner_email)
        return WebsiteDeploymentResponse.model_validate(dep)
    except DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DeploymentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/deployments/{deployment_id}/approve",
    response_model=WebsiteDeploymentResponse,
    summary="Owner Gate 5 approval for a production deployment",
)
async def approve_deployment(
    deployment_id: uuid.UUID,
    payload: WebsiteDeploymentApproveRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WebsiteDeploymentResponse:
    verify_owner_access(owner_email)
    try:
        dep = await WebsiteDeploymentService.approve_deployment(
            db=db,
            deployment_id=deployment_id,
            owner_id=owner_email,
            notes=payload.notes,
        )
        await db.commit()
        await db.refresh(dep)
        return WebsiteDeploymentResponse.model_validate(dep)
    except DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DeploymentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except DeploymentEligibilityError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Deployment eligibility check failed", "reasons": exc.reasons},
        )
    except DeploymentInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post(
    "/deployments/{deployment_id}/execute",
    response_model=WebsiteDeploymentResponse,
    summary="Execute an approved deployment",
)
async def execute_deployment(
    deployment_id: uuid.UUID,
    payload: WebsiteDeploymentExecuteRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WebsiteDeploymentResponse:
    verify_owner_access(owner_email)
    try:
        dep = await WebsiteDeploymentService.execute_deployment(
            db=db,
            deployment_id=deployment_id,
            owner_id=owner_email,
            force_mock=payload.force_mock,
        )
        await db.commit()
        await db.refresh(dep)
        return WebsiteDeploymentResponse.model_validate(dep)
    except DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DeploymentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except DeploymentApprovalRequiredError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except DeploymentInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        log.exception("execute_deployment_endpoint_failed", deployment_id=str(deployment_id))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.post(
    "/deployments/{deployment_id}/cancel",
    response_model=WebsiteDeploymentResponse,
    summary="Cancel a pending or unexecuted deployment",
)
async def cancel_deployment(
    deployment_id: uuid.UUID,
    payload: WebsiteDeploymentCancelRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WebsiteDeploymentResponse:
    verify_owner_access(owner_email)
    try:
        dep = await WebsiteDeploymentService.cancel_deployment(
            db=db,
            deployment_id=deployment_id,
            owner_id=owner_email,
            reason=payload.reason,
        )
        await db.commit()
        await db.refresh(dep)
        return WebsiteDeploymentResponse.model_validate(dep)
    except DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DeploymentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except DeploymentInvalidStateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ── Custom Domains & DNS ──────────────────────────────────────────────────────

@router.post(
    "/deployments/{deployment_id}/domains",
    response_model=WebsiteDeploymentResponse,
    summary="Bind a custom domain and get DNS records",
)
async def configure_custom_domain(
    deployment_id: uuid.UUID,
    payload: WebsiteDeploymentDomainRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WebsiteDeploymentResponse:
    verify_owner_access(owner_email)
    try:
        dep = await WebsiteDeploymentService.configure_custom_domain(
            db=db,
            deployment_id=deployment_id,
            owner_id=owner_email,
            domain=payload.domain,
        )
        await db.commit()
        await db.refresh(dep)
        return WebsiteDeploymentResponse.model_validate(dep)
    except DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DeploymentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except DeploymentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/deployments/{deployment_id}/domains/verify",
    response_model=WebsiteDeploymentResponse,
    summary="Verify DNS propagation and SSL status for custom domain",
)
async def verify_custom_domain(
    deployment_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> WebsiteDeploymentResponse:
    verify_owner_access(owner_email)
    try:
        dep = await WebsiteDeploymentService.verify_custom_domain(
            db=db,
            deployment_id=deployment_id,
            owner_id=owner_email,
        )
        await db.commit()
        await db.refresh(dep)
        return WebsiteDeploymentResponse.model_validate(dep)
    except DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except DeploymentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except DeploymentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
