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
from schemas.website_specification import (
    WebsiteGenerationDetailResponse,
    WebsiteGenerationListResponse,
    WebsiteGenerationResponse,
)
from services.website_generation_service import (
    WebsiteGenerationEligibilityError,
    WebsiteGenerationFailedError,
    WebsiteGenerationNotFoundError,
    WebsiteGenerationOwnershipError,
    WebsiteGenerationPRDMismatchError,
    WebsiteGenerationService,
    WebsiteGenerationSessionNotFoundError,
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


# ── Website Generation Endpoints (Phase 6.2) ──────────────────────────────────

@router.post(
    "/build-sessions/{session_id}/generations",
    response_model=WebsiteGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger AI website specification generation for a READY build session",
)
async def create_website_generation(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteGenerationResponse:
    """
    Trigger AI website specification generation.
    Prerequisites:
    - Session must be in READY status.
    - Associated project must be READY_FOR_BUILD with an approved PRD.
    - Owner authentication enforced via JWT.
    """
    verify_owner_access(owner_email)
    try:
        generation = await WebsiteGenerationService.generate_specification(
            db=db,
            session_id=session_id,
            owner_id=owner_email,
        )
        return WebsiteGenerationResponse(
            id=generation.id,
            build_session_id=generation.build_session_id,
            project_id=generation.project_id,
            owner_id=generation.owner_id,
            source_prd_id=generation.source_prd_id,
            source_prd_version=generation.source_prd_version,
            generation_version=generation.generation_version,
            status=generation.status.value,
            provider=generation.provider,
            model=generation.model,
            specification_artifact_id=generation.specification_artifact_id,
            error_code=generation.error_code,
            error_message=generation.error_message,
            started_at=generation.started_at,
            completed_at=generation.completed_at,
            metadata=generation.generation_metadata,
            created_at=generation.created_at,
            updated_at=generation.updated_at,
        )
    except WebsiteGenerationSessionNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except WebsiteGenerationOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (WebsiteGenerationEligibilityError, WebsiteGenerationPRDMismatchError) as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except WebsiteGenerationFailedError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/build-sessions/{session_id}/generations",
    response_model=WebsiteGenerationListResponse,
    summary="List all website specification generations for a build session",
)
async def list_website_generations(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteGenerationListResponse:
    """List historical generations for a build session ordered by version desc."""
    verify_owner_access(owner_email)
    try:
        items = await WebsiteGenerationService.list_generations(
            db=db,
            session_id=session_id,
            owner_id=owner_email,
        )
        responses = [
            WebsiteGenerationResponse(
                id=g.id,
                build_session_id=g.build_session_id,
                project_id=g.project_id,
                owner_id=g.owner_id,
                source_prd_id=g.source_prd_id,
                source_prd_version=g.source_prd_version,
                generation_version=g.generation_version,
                status=g.status.value,
                provider=g.provider,
                model=g.model,
                specification_artifact_id=g.specification_artifact_id,
                error_code=g.error_code,
                error_message=g.error_message,
                started_at=g.started_at,
                completed_at=g.completed_at,
                metadata=g.generation_metadata,
                created_at=g.created_at,
                updated_at=g.updated_at,
            )
            for g in items
        ]
        completed = sum(1 for g in items if g.status == "completed")
        failed = sum(1 for g in items if g.status == "failed")
        active = sum(1 for g in items if g.status in ("pending", "generating", "validating"))

        return WebsiteGenerationListResponse(
            items=responses,
            total=len(responses),
            completed_count=completed,
            failed_count=failed,
            active_count=active,
        )
    except WebsiteGenerationSessionNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except WebsiteGenerationOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/generations/{generation_id}",
    response_model=WebsiteGenerationDetailResponse,
    summary="Retrieve details and specification artifact for a generation",
)
async def get_website_generation(
    generation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteGenerationDetailResponse:
    """Retrieve full generation details including validated WebsiteSpecification."""
    verify_owner_access(owner_email)
    try:
        generation, spec = await WebsiteGenerationService.get_generation(
            db=db,
            generation_id=generation_id,
            owner_id=owner_email,
        )
        return WebsiteGenerationDetailResponse(
            id=generation.id,
            build_session_id=generation.build_session_id,
            project_id=generation.project_id,
            owner_id=generation.owner_id,
            source_prd_id=generation.source_prd_id,
            source_prd_version=generation.source_prd_version,
            generation_version=generation.generation_version,
            status=generation.status.value,
            provider=generation.provider,
            model=generation.model,
            specification_artifact_id=generation.specification_artifact_id,
            error_code=generation.error_code,
            error_message=generation.error_message,
            started_at=generation.started_at,
            completed_at=generation.completed_at,
            metadata=generation.generation_metadata,
            created_at=generation.created_at,
            updated_at=generation.updated_at,
            specification=spec,
            project_name=generation.project.project_name if generation.project else None,
            project_slug=generation.project.project_slug if generation.project else None,
        )
    except WebsiteGenerationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except WebsiteGenerationOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/generations/{generation_id}/cancel",
    response_model=WebsiteGenerationResponse,
    summary="Cancel an active generation",
)
async def cancel_website_generation(
    generation_id: uuid.UUID,
    request: Optional[BuildSessionCancelRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteGenerationResponse:
    """Cancel a pending or generating execution."""
    verify_owner_access(owner_email)
    try:
        generation = await WebsiteGenerationService.cancel_generation(
            db=db,
            generation_id=generation_id,
            owner_id=owner_email,
            reason=request.reason if request else None,
        )
        return WebsiteGenerationResponse(
            id=generation.id,
            build_session_id=generation.build_session_id,
            project_id=generation.project_id,
            owner_id=generation.owner_id,
            source_prd_id=generation.source_prd_id,
            source_prd_version=generation.source_prd_version,
            generation_version=generation.generation_version,
            status=generation.status.value,
            provider=generation.provider,
            model=generation.model,
            specification_artifact_id=generation.specification_artifact_id,
            error_code=generation.error_code,
            error_message=generation.error_message,
            started_at=generation.started_at,
            completed_at=generation.completed_at,
            metadata=generation.generation_metadata,
            created_at=generation.created_at,
            updated_at=generation.updated_at,
        )
    except WebsiteGenerationNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except WebsiteGenerationOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except WebsiteGenerationEligibilityError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
