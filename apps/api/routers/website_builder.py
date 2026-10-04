"""
Website Builder Router — Phase 6 Stage 6.1.

Provides authenticated, owner-scoped endpoints for:
- Creating or retrieving an active build session for a project
- Listing build sessions for a project
- Retrieving detailed build session data and artifacts
- Transitioning build session lifecycle state (plan, ready, pause, cancel)

STRICT BOUNDARIES:
- NO website generator, code generation, GitHub, or Vercel endpoints.
- All endpoints enforce JWT owner authentication via require_owner.
"""
from __future__ import annotations

from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from core.config import settings
from core.database import get_db
from models.website_builder import WebsiteBuildSessionStatus
from routers.auth import require_owner
from schemas.website_builder import (
    BuildSessionCancelRequest,
    BuildSessionPauseRequest,
    BuildSessionTransitionRequest,
    WebsiteBuildSessionDetailResponse,
    WebsiteBuildSessionListResponse,
    WebsiteBuildSessionResponse,
)
from services.website_build_session_service import (
    BuildSessionError,
    BuildSessionInvalidStateTransitionError,
    BuildSessionNotFoundError,
    BuildSessionOwnershipError,
    BuildSessionPRDIneligibleError,
    BuildSessionProjectIneligibleError,
    BuildSessionTerminalStateError,
    WebsiteBuildSessionService,
)

router = APIRouter()
log = structlog.get_logger(__name__)


def verify_owner_access(owner_email: str) -> None:
    """Verify authenticated caller matches configured agency owner."""
    if settings.OWNER_EMAIL and owner_email.lower().strip() != settings.OWNER_EMAIL.lower().strip():
        log.warning("Unauthorized owner access attempt on Website Builder API", caller=owner_email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not authorized to access this agency's website builder resources.",
        )


# ── Project Scoped Endpoints ──────────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/build-sessions",
    response_model=WebsiteBuildSessionResponse,
    summary="Create or retrieve active Website Build Session for an eligible project",
)
async def create_build_session(
    project_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteBuildSessionResponse:
    """
    Create a controlled build session workspace:
    - Requires Gate 4 APPROVED PRD and project in READY_FOR_BUILD status.
    - Idempotent: returns existing active build session if present.
    """
    verify_owner_access(owner_email)
    try:
        session, created = await WebsiteBuildSessionService.get_or_create_build_session(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
        )
        await db.commit()
        response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return WebsiteBuildSessionResponse(
            id=session.id,
            project_id=session.project_id,
            owner_id=session.owner_id,
            status=session.status,
            build_version=session.build_version,
            started_at=session.started_at,
            completed_at=session.completed_at,
            failure_reason=session.failure_reason,
            metadata=session.build_metadata,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
    except BuildSessionOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (BuildSessionProjectIneligibleError, BuildSessionPRDIneligibleError) as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except BuildSessionError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/projects/{project_id}/build-sessions",
    response_model=WebsiteBuildSessionListResponse,
    summary="List build sessions for a project",
)
async def list_build_sessions_for_project(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteBuildSessionListResponse:
    """List all build sessions for a project."""
    verify_owner_access(owner_email)
    try:
        return await WebsiteBuildSessionService.list_build_sessions_for_project(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
        )
    except BuildSessionOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except BuildSessionProjectIneligibleError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ── Session Scoped Endpoints ──────────────────────────────────────────────────

@router.get(
    "/build-sessions/{session_id}",
    response_model=WebsiteBuildSessionDetailResponse,
    summary="Retrieve build session details and artifacts",
)
async def get_build_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteBuildSessionDetailResponse:
    """Retrieve single build session with PRD snapshot reference and artifact records."""
    verify_owner_access(owner_email)
    try:
        detail = await WebsiteBuildSessionService.get_build_session(
            db=db,
            session_id=session_id,
            owner_id=owner_email,
        )
        await db.commit()
        return detail
    except BuildSessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BuildSessionOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/build-sessions/{session_id}/plan",
    response_model=WebsiteBuildSessionResponse,
    summary="Transition session from CREATED to PLANNED",
)
async def plan_build_session(
    session_id: uuid.UUID,
    request: Optional[BuildSessionTransitionRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteBuildSessionResponse:
    """Transition build session state to PLANNED."""
    verify_owner_access(owner_email)
    try:
        session = await WebsiteBuildSessionService.transition_session_status(
            db=db,
            session_id=session_id,
            owner_id=owner_email,
            target_status=WebsiteBuildSessionStatus.PLANNED,
            reason_or_notes=request.notes if request else None,
        )
        await db.commit()
        return WebsiteBuildSessionResponse(
            id=session.id,
            project_id=session.project_id,
            owner_id=session.owner_id,
            status=session.status,
            build_version=session.build_version,
            started_at=session.started_at,
            completed_at=session.completed_at,
            failure_reason=session.failure_reason,
            metadata=session.build_metadata,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
    except BuildSessionNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BuildSessionOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (BuildSessionInvalidStateTransitionError, BuildSessionTerminalStateError) as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/build-sessions/{session_id}/ready",
    response_model=WebsiteBuildSessionResponse,
    summary="Transition session from PLANNED to READY",
)
async def ready_build_session(
    session_id: uuid.UUID,
    request: Optional[BuildSessionTransitionRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteBuildSessionResponse:
    """Transition build session state to READY."""
    verify_owner_access(owner_email)
    try:
        session = await WebsiteBuildSessionService.transition_session_status(
            db=db,
            session_id=session_id,
            owner_id=owner_email,
            target_status=WebsiteBuildSessionStatus.READY,
            reason_or_notes=request.notes if request else None,
        )
        await db.commit()
        return WebsiteBuildSessionResponse(
            id=session.id,
            project_id=session.project_id,
            owner_id=session.owner_id,
            status=session.status,
            build_version=session.build_version,
            started_at=session.started_at,
            completed_at=session.completed_at,
            failure_reason=session.failure_reason,
            metadata=session.build_metadata,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
    except BuildSessionNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BuildSessionOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (BuildSessionInvalidStateTransitionError, BuildSessionTerminalStateError) as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/build-sessions/{session_id}/pause",
    response_model=WebsiteBuildSessionResponse,
    summary="Transition session from IN_PROGRESS to PAUSED",
)
async def pause_build_session(
    session_id: uuid.UUID,
    request: Optional[BuildSessionPauseRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteBuildSessionResponse:
    """Transition build session state to PAUSED."""
    verify_owner_access(owner_email)
    try:
        session = await WebsiteBuildSessionService.transition_session_status(
            db=db,
            session_id=session_id,
            owner_id=owner_email,
            target_status=WebsiteBuildSessionStatus.PAUSED,
            reason_or_notes=request.reason if request else None,
        )
        await db.commit()
        return WebsiteBuildSessionResponse(
            id=session.id,
            project_id=session.project_id,
            owner_id=session.owner_id,
            status=session.status,
            build_version=session.build_version,
            started_at=session.started_at,
            completed_at=session.completed_at,
            failure_reason=session.failure_reason,
            metadata=session.build_metadata,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
    except BuildSessionNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BuildSessionOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (BuildSessionInvalidStateTransitionError, BuildSessionTerminalStateError) as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/build-sessions/{session_id}/cancel",
    response_model=WebsiteBuildSessionResponse,
    summary="Cancel a build session (terminal state)",
)
async def cancel_build_session(
    session_id: uuid.UUID,
    request: Optional[BuildSessionCancelRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteBuildSessionResponse:
    """Explicitly cancel a build session."""
    verify_owner_access(owner_email)
    try:
        session = await WebsiteBuildSessionService.transition_session_status(
            db=db,
            session_id=session_id,
            owner_id=owner_email,
            target_status=WebsiteBuildSessionStatus.CANCELLED,
            reason_or_notes=request.reason if request else None,
        )
        await db.commit()
        return WebsiteBuildSessionResponse(
            id=session.id,
            project_id=session.project_id,
            owner_id=session.owner_id,
            status=session.status,
            build_version=session.build_version,
            started_at=session.started_at,
            completed_at=session.completed_at,
            failure_reason=session.failure_reason,
            metadata=session.build_metadata,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
    except BuildSessionNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except BuildSessionOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (BuildSessionInvalidStateTransitionError, BuildSessionTerminalStateError) as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
