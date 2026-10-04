"""
Projects Router — Phase 5 Stage 5.4.

Provides authenticated, owner-scoped endpoints for:
- Creating a Project from a Gate 4 APPROVED ClientPRD
- Listing all Projects with metrics and filtering
- Retrieving detailed Project handoff metadata
- Updating safe mutable Project attributes

All endpoints enforce:
- JWT owner authentication via require_owner
- IDOR protection: owner_id from JWT only, never from request body
- Gate 4 safeguards: only APPROVED PRDs can form projects; approved PRD version is preserved
- Fail-closed error handling and audit logging
"""
from __future__ import annotations

from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from core.config import settings
from core.database import get_db
from models.project import ProjectStatus
from routers.auth import require_owner
from schemas.project import (
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)
from services.project_service import (
    PRDInvalidStateError,
    PRDNotApprovedError,
    ProjectAlreadyExistsError,
    ProjectError,
    ProjectImmutableFieldError,
    ProjectInvalidStatusTransitionError,
    ProjectNotFoundError,
    ProjectOwnershipError,
    ProjectService,
    ProjectValidationError,
)

router = APIRouter()
log = structlog.get_logger(__name__)


def verify_owner_access(owner_email: str) -> None:
    """
    IDOR Protection: verify the authenticated JWT owner matches the configured agency owner.
    """
    if settings.OWNER_EMAIL and owner_email.lower().strip() != settings.OWNER_EMAIL.lower().strip():
        log.warning(
            "Unauthorized owner access attempt on Projects API",
            caller=owner_email,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not authorized to access this agency's project resources.",
        )


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new Project from an Approved PRD (Gate 4)",
)
async def create_project(
    request: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> ProjectResponse:
    """
    Controlled project creation workflow:
    - Requires authenticated owner
    - Requires Gate 4 APPROVED PRD
    - Enforces database idempotency (one project per approved PRD)
    - Records comprehensive audit logs
    """
    verify_owner_access(owner_email)
    try:
        project = await ProjectService.create_project(
            db=db,
            owner_id=owner_email,
            request=request,
        )
        await db.commit()
        return ProjectResponse.model_validate(project)
    except ProjectAlreadyExistsError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": str(e),
                "existing_project_id": str(e.existing_project_id) if e.existing_project_id else None,
            },
        )
    except PRDNotApprovedError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except PRDInvalidStateError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ProjectOwnershipError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except ProjectValidationError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except ProjectError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List all agency projects with metric counts",
)
async def list_projects(
    status: Optional[ProjectStatus] = Query(default=None, description="Filter by project status"),
    search: Optional[str] = Query(default=None, description="Search by project name or slug"),
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> ProjectListResponse:
    """List all projects belonging to the authenticated owner."""
    verify_owner_access(owner_email)
    return await ProjectService.list_projects(
        db=db,
        owner_id=owner_email,
        status_filter=status,
        search=search,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="Get full project details, lead info, and Phase 6 handoff metadata",
)
async def get_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> ProjectDetailResponse:
    """Retrieve a single project by ID with enriched business and PRD handoff data."""
    verify_owner_access(owner_email)
    try:
        project_detail = await ProjectService.get_project(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
        )
        await db.commit()
        return project_detail
    except ProjectNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ProjectOwnershipError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update safe mutable fields on a project",
)
async def update_project(
    project_id: uuid.UUID,
    request: ProjectUpdateRequest,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> ProjectResponse:
    """Update mutable project attributes (project_name, permitted status, safe phase_metadata)."""
    verify_owner_access(owner_email)
    try:
        project = await ProjectService.update_project(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
            request=request,
        )
        await db.commit()
        return ProjectResponse.model_validate(project)
    except ProjectNotFoundError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ProjectOwnershipError as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except (ProjectInvalidStatusTransitionError, ProjectImmutableFieldError, ProjectValidationError) as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
