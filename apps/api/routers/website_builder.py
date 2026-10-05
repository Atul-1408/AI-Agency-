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
from schemas.design_blueprint import (
    DesignBlueprintCancelRequest,
    DesignBlueprintDetailResponse,
    DesignBlueprintListResponse,
    DesignBlueprintResponse,
)
from services.design_blueprint_service import (
    DesignBlueprintEligibilityError,
    DesignBlueprintFailedError,
    DesignBlueprintNotFoundError,
    DesignBlueprintOwnershipError,
    DesignBlueprintPRDMismatchError,
    DesignBlueprintService,
    DesignBlueprintValidationError,
)
from schemas.code_generation import (
    WebsiteCodeGenerationCancelRequest,
    WebsiteCodeGenerationCreateRequest,
    WebsiteCodeGenerationDetailResponse,
    WebsiteCodeGenerationFilesResponse,
    WebsiteCodeGenerationListResponse,
    WebsiteCodeGenerationManifestResponse,
    WebsiteCodeGenerationResponse,
)
from services.code_generation_service import (
    CodeGenerationEligibilityError,
    CodeGenerationFailedError,
    CodeGenerationNotFoundError,
    CodeGenerationOwnershipError,
    CodeGenerationPRDMismatchError,
    CodeGenerationValidationFailureError,
    WebsiteCodeGenerationService,
)
from fastapi.responses import HTMLResponse
from schemas.website_preview_edit import (
    WebsiteEditCancelRequest,
    WebsiteEditCreateRequest,
    WebsiteEditDetailResponse,
    WebsiteEditListResponse,
    WebsiteEditResponse,
    WebsiteEditVersionResponse,
    WebsitePreviewCreateRequest,
    WebsitePreviewListResponse,
    WebsitePreviewResponse,
    WebsitePreviewStatusResponse,
    WebsiteVersionListResponse,
    WebsiteVersionRollbackResponse,
)
from services.website_preview_service import (
    PreviewError,
    PreviewIneligibleError,
    PreviewNotFoundError,
    PreviewOwnershipError,
    WebsitePreviewService,
)
from services.website_editing_service import (
    ConcurrentEditConflictError,
    EditError,
    EditIneligibleError,
    EditNotFoundError,
    EditOwnershipError,
    EditValidationFailureError,
    StaleBaseVersionConflictError,
    WebsiteEditingService,
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


# ── Phase 6.3 Design Blueprint Endpoints ────────────────────────────────────────


@router.post(
    "/generations/{generation_id}/blueprints",
    response_model=DesignBlueprintResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate an implementation-ready design blueprint from a completed generation",
)
async def create_design_blueprint(
    generation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> DesignBlueprintResponse:
    """Generate DesignBlueprint from validated WebsiteSpecification and PRD."""
    verify_owner_access(owner_email)
    try:
        blueprint = await DesignBlueprintService.create_design_blueprint(
            db=db,
            generation_id=generation_id,
            owner_id=owner_email,
        )
        return DesignBlueprintResponse(
            id=blueprint.id,
            build_session_id=blueprint.build_session_id,
            project_id=blueprint.project_id,
            owner_id=blueprint.owner_id,
            source_generation_id=blueprint.source_generation_id,
            source_generation_version=blueprint.source_generation_version,
            blueprint_version=blueprint.blueprint_version,
            status=blueprint.status.value,
            specification_artifact_id=blueprint.specification_artifact_id,
            error_code=blueprint.error_code,
            error_message=blueprint.error_message,
            started_at=blueprint.started_at,
            completed_at=blueprint.completed_at,
            metadata=blueprint.blueprint_metadata,
            created_at=blueprint.created_at,
            updated_at=blueprint.updated_at,
        )
    except DesignBlueprintNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DesignBlueprintOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except (DesignBlueprintPRDMismatchError, DesignBlueprintEligibilityError) as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except DesignBlueprintValidationError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except DesignBlueprintFailedError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get(
    "/generations/{generation_id}/blueprints",
    response_model=DesignBlueprintListResponse,
    summary="List all design blueprints for a generation",
)
async def list_design_blueprints(
    generation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> DesignBlueprintListResponse:
    """Retrieve all design blueprints created for the specified generation."""
    verify_owner_access(owner_email)
    try:
        items = await DesignBlueprintService.list_blueprints_for_generation(
            db=db,
            generation_id=generation_id,
            owner_id=owner_email,
        )
        responses = [
            DesignBlueprintResponse(
                id=b.id,
                build_session_id=b.build_session_id,
                project_id=b.project_id,
                owner_id=b.owner_id,
                source_generation_id=b.source_generation_id,
                source_generation_version=b.source_generation_version,
                blueprint_version=b.blueprint_version,
                status=b.status.value,
                specification_artifact_id=b.specification_artifact_id,
                error_code=b.error_code,
                error_message=b.error_message,
                started_at=b.started_at,
                completed_at=b.completed_at,
                metadata=b.blueprint_metadata,
                created_at=b.created_at,
                updated_at=b.updated_at,
            )
            for b in items
        ]
        completed = sum(1 for b in items if b.status.value == "completed")
        failed = sum(1 for b in items if b.status.value == "failed")
        active = sum(1 for b in items if b.status.value in ("pending", "generating", "validating"))

        return DesignBlueprintListResponse(
            items=responses,
            total=len(responses),
            completed_count=completed,
            failed_count=failed,
            active_count=active,
        )
    except DesignBlueprintNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DesignBlueprintOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/design-blueprints/{blueprint_id}",
    response_model=DesignBlueprintDetailResponse,
    summary="Retrieve details and blueprint payload for a design blueprint",
)
async def get_design_blueprint(
    blueprint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> DesignBlueprintDetailResponse:
    """Retrieve full design blueprint details including the structured WebsiteDesignBlueprint."""
    verify_owner_access(owner_email)
    try:
        blueprint, bp_obj = await DesignBlueprintService.get_design_blueprint(
            db=db,
            blueprint_id=blueprint_id,
            owner_id=owner_email,
        )
        return DesignBlueprintDetailResponse(
            id=blueprint.id,
            build_session_id=blueprint.build_session_id,
            project_id=blueprint.project_id,
            owner_id=blueprint.owner_id,
            source_generation_id=blueprint.source_generation_id,
            source_generation_version=blueprint.source_generation_version,
            blueprint_version=blueprint.blueprint_version,
            status=blueprint.status.value,
            specification_artifact_id=blueprint.specification_artifact_id,
            error_code=blueprint.error_code,
            error_message=blueprint.error_message,
            started_at=blueprint.started_at,
            completed_at=blueprint.completed_at,
            metadata=blueprint.blueprint_metadata,
            created_at=blueprint.created_at,
            updated_at=blueprint.updated_at,
            blueprint=bp_obj,
            project_name=blueprint.project.project_name if blueprint.project else None,
            project_slug=blueprint.project.project_slug if blueprint.project else None,
        )
    except DesignBlueprintNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DesignBlueprintOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/design-blueprints/{blueprint_id}/cancel",
    response_model=DesignBlueprintResponse,
    summary="Cancel an active design blueprint generation",
)
async def cancel_design_blueprint(
    blueprint_id: uuid.UUID,
    request: Optional[DesignBlueprintCancelRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> DesignBlueprintResponse:
    """Cancel a pending, generating, or validating design blueprint generation."""
    verify_owner_access(owner_email)
    try:
        blueprint = await DesignBlueprintService.cancel_design_blueprint(
            db=db,
            blueprint_id=blueprint_id,
            owner_id=owner_email,
            reason=request.reason if request else None,
        )
        return DesignBlueprintResponse(
            id=blueprint.id,
            build_session_id=blueprint.build_session_id,
            project_id=blueprint.project_id,
            owner_id=blueprint.owner_id,
            source_generation_id=blueprint.source_generation_id,
            source_generation_version=blueprint.source_generation_version,
            blueprint_version=blueprint.blueprint_version,
            status=blueprint.status.value,
            specification_artifact_id=blueprint.specification_artifact_id,
            error_code=blueprint.error_code,
            error_message=blueprint.error_message,
            started_at=blueprint.started_at,
            completed_at=blueprint.completed_at,
            metadata=blueprint.blueprint_metadata,
            created_at=blueprint.created_at,
            updated_at=blueprint.updated_at,
        )
    except DesignBlueprintNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except DesignBlueprintOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except DesignBlueprintEligibilityError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ── Phase 6.4 Code Generation Endpoints ────────────────────────────────────────

@router.post(
    "/build-sessions/{session_id}/code-generations",
    response_model=WebsiteCodeGenerationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate Next.js source code for an eligible build session",
)
async def create_code_generation(
    session_id: uuid.UUID,
    request: Optional[WebsiteCodeGenerationCreateRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteCodeGenerationResponse:
    """
    Executes actual Next.js website code generation from a completed DesignBlueprint.
    Strictly enforces owner authentication, READY_FOR_BUILD status, completed Blueprint,
    deterministic static validation, and isolated workspace storage.
    """
    verify_owner_access(owner_email)
    try:
        blueprint_id = request.design_blueprint_id if request else None
        code_gen = await WebsiteCodeGenerationService.generate_code(
            db=db,
            session_id=session_id,
            owner_id=owner_email,
            blueprint_id=blueprint_id,
        )
        return WebsiteCodeGenerationResponse(
            id=code_gen.id,
            project_id=code_gen.project_id,
            build_session_id=code_gen.build_session_id,
            website_generation_id=code_gen.website_generation_id,
            design_blueprint_id=code_gen.design_blueprint_id,
            approved_prd_id=code_gen.approved_prd_id,
            owner_id=code_gen.owner_id,
            prd_version=code_gen.prd_version,
            code_generation_version=code_gen.code_generation_version,
            status=code_gen.status.value,
            provider=code_gen.provider,
            model=code_gen.model,
            source_checksum=code_gen.source_checksum,
            file_count=code_gen.file_count,
            source_artifact_id=code_gen.source_artifact_id,
            error_code=code_gen.error_code,
            error_message=code_gen.error_message,
            started_at=code_gen.started_at,
            completed_at=code_gen.completed_at,
            failed_at=code_gen.failed_at,
            metadata=code_gen.generation_metadata,
            created_at=code_gen.created_at,
            updated_at=code_gen.updated_at,
        )
    except CodeGenerationNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except CodeGenerationOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except CodeGenerationPRDMismatchError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except CodeGenerationValidationFailureError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except CodeGenerationEligibilityError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except CodeGenerationFailedError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get(
    "/build-sessions/{session_id}/code-generations",
    response_model=WebsiteCodeGenerationListResponse,
    summary="List code generations for a build session",
)
async def list_code_generations_for_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteCodeGenerationListResponse:
    """Lists all code generations for a build session ordered by version descending."""
    verify_owner_access(owner_email)
    try:
        items = await WebsiteCodeGenerationService.list_code_generations(
            db=db,
            session_id=session_id,
            owner_id=owner_email,
        )
        responses = [
            WebsiteCodeGenerationResponse(
                id=g.id,
                project_id=g.project_id,
                build_session_id=g.build_session_id,
                website_generation_id=g.website_generation_id,
                design_blueprint_id=g.design_blueprint_id,
                approved_prd_id=g.approved_prd_id,
                owner_id=g.owner_id,
                prd_version=g.prd_version,
                code_generation_version=g.code_generation_version,
                status=g.status.value,
                provider=g.provider,
                model=g.model,
                source_checksum=g.source_checksum,
                file_count=g.file_count,
                source_artifact_id=g.source_artifact_id,
                error_code=g.error_code,
                error_message=g.error_message,
                started_at=g.started_at,
                completed_at=g.completed_at,
                failed_at=g.failed_at,
                metadata=g.generation_metadata,
                created_at=g.created_at,
                updated_at=g.updated_at,
            )
            for g in items
        ]
        completed = sum(1 for g in items if g.status.value == "completed")
        failed = sum(1 for g in items if g.status.value == "failed")
        active = sum(1 for g in items if g.status.value in ("pending", "generating", "validating"))

        return WebsiteCodeGenerationListResponse(
            items=responses,
            total=len(responses),
            completed_count=completed,
            failed_count=failed,
            active_count=active,
        )
    except CodeGenerationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except CodeGenerationOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/code-generations/{generation_id}",
    response_model=WebsiteCodeGenerationDetailResponse,
    summary="Retrieve code generation details and manifest",
)
async def get_code_generation(
    generation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteCodeGenerationDetailResponse:
    """Retrieve full details of a specific code generation execution."""
    verify_owner_access(owner_email)
    try:
        record, manifest = await WebsiteCodeGenerationService.get_code_generation(
            db=db,
            generation_id=generation_id,
            owner_id=owner_email,
        )
        files_summary = manifest.get("files") if manifest else None
        return WebsiteCodeGenerationDetailResponse(
            id=record.id,
            project_id=record.project_id,
            build_session_id=record.build_session_id,
            website_generation_id=record.website_generation_id,
            design_blueprint_id=record.design_blueprint_id,
            approved_prd_id=record.approved_prd_id,
            owner_id=record.owner_id,
            prd_version=record.prd_version,
            code_generation_version=record.code_generation_version,
            status=record.status.value,
            provider=record.provider,
            model=record.model,
            source_checksum=record.source_checksum,
            file_count=record.file_count,
            source_artifact_id=record.source_artifact_id,
            error_code=record.error_code,
            error_message=record.error_message,
            started_at=record.started_at,
            completed_at=record.completed_at,
            failed_at=record.failed_at,
            metadata=record.generation_metadata,
            created_at=record.created_at,
            updated_at=record.updated_at,
            project_name=record.project.project_name if record.project else None,
            project_slug=record.project.project_slug if record.project else None,
            manifest=manifest,
            files_summary=files_summary,
        )
    except CodeGenerationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except CodeGenerationOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/code-generations/{generation_id}/cancel",
    response_model=WebsiteCodeGenerationResponse,
    summary="Cancel an active code generation",
)
async def cancel_code_generation(
    generation_id: uuid.UUID,
    request: Optional[WebsiteCodeGenerationCancelRequest] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteCodeGenerationResponse:
    """Cancels a pending, generating, or validating code generation execution."""
    verify_owner_access(owner_email)
    try:
        record = await WebsiteCodeGenerationService.cancel_code_generation(
            db=db,
            generation_id=generation_id,
            owner_id=owner_email,
            reason=request.reason if request else None,
        )
        return WebsiteCodeGenerationResponse(
            id=record.id,
            project_id=record.project_id,
            build_session_id=record.build_session_id,
            website_generation_id=record.website_generation_id,
            design_blueprint_id=record.design_blueprint_id,
            approved_prd_id=record.approved_prd_id,
            owner_id=record.owner_id,
            prd_version=record.prd_version,
            code_generation_version=record.code_generation_version,
            status=record.status.value,
            provider=record.provider,
            model=record.model,
            source_checksum=record.source_checksum,
            file_count=record.file_count,
            source_artifact_id=record.source_artifact_id,
            error_code=record.error_code,
            error_message=record.error_message,
            started_at=record.started_at,
            completed_at=record.completed_at,
            failed_at=record.failed_at,
            metadata=record.generation_metadata,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
    except CodeGenerationNotFoundError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except CodeGenerationOwnershipError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except CodeGenerationEligibilityError as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get(
    "/code-generations/{generation_id}/manifest",
    response_model=WebsiteCodeGenerationManifestResponse,
    summary="Retrieve structured file manifest for a completed code generation",
)
async def get_code_generation_manifest(
    generation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteCodeGenerationManifestResponse:
    """Retrieves file manifest, checksums, entrypoints, and routes."""
    verify_owner_access(owner_email)
    try:
        record, manifest = await WebsiteCodeGenerationService.get_code_generation(
            db=db,
            generation_id=generation_id,
            owner_id=owner_email,
        )
        if not manifest:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manifest not found for this generation.")

        return WebsiteCodeGenerationManifestResponse(
            generation_id=record.id,
            version=record.code_generation_version,
            framework=manifest.get("framework", "nextjs"),
            language=manifest.get("language", "typescript"),
            source_checksum=manifest.get("source_checksum", record.source_checksum or ""),
            file_count=manifest.get("file_count", record.file_count),
            entrypoints=manifest.get("entrypoints", []),
            routes=manifest.get("routes", []),
            components=manifest.get("components", []),
            files=manifest.get("files", []),
        )
    except CodeGenerationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except CodeGenerationOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/code-generations/{generation_id}/files",
    response_model=WebsiteCodeGenerationFilesResponse,
    summary="Retrieve generated source files for a code generation",
)
async def get_code_generation_files(
    generation_id: uuid.UUID,
    path: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteCodeGenerationFilesResponse:
    """Retrieves all generated files or a specific file matching query path."""
    verify_owner_access(owner_email)
    try:
        files = await WebsiteCodeGenerationService.get_code_generation_files(
            db=db,
            generation_id=generation_id,
            owner_id=owner_email,
            path=path,
        )
        return WebsiteCodeGenerationFilesResponse(
            generation_id=generation_id,
            files=files,
        )
    except CodeGenerationNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except CodeGenerationOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# ── Phase 6.5 Serializers ─────────────────────────────────────────────────────

def _serialize_preview(preview: Any) -> WebsitePreviewResponse:
    return WebsitePreviewResponse(
        id=preview.id,
        project_id=preview.project_id,
        build_session_id=preview.build_session_id,
        code_generation_id=preview.code_generation_id,
        version=preview.current_version,
        status=preview.status.value,
        preview_token=preview.preview_token,
        preview_url=f"/api/v1/previews/{preview.id}/render",
        port=preview.port,
        workspace_reference=preview.workspace_reference,
        started_at=preview.started_at,
        stopped_at=preview.stopped_at,
        expires_at=preview.expires_at,
        last_error=preview.last_error,
        metadata=preview.preview_metadata,
        created_at=preview.created_at,
    )


def _serialize_edit(edit: Any) -> WebsiteEditResponse:
    return WebsiteEditResponse(
        id=edit.id,
        project_id=edit.project_id,
        preview_id=edit.preview_id,
        base_code_generation_id=edit.base_code_generation_id,
        base_version=edit.base_version,
        status=edit.status.value,
        owner_request=edit.owner_request,
        error_code=edit.error_code,
        error_message=edit.error_message,
        started_at=edit.started_at,
        completed_at=edit.completed_at,
        metadata=edit.edit_metadata,
        created_at=edit.created_at,
    )


def _serialize_version(ver: Any) -> WebsiteEditVersionResponse:
    return WebsiteEditVersionResponse(
        id=ver.id,
        project_id=ver.project_id,
        edit_session_id=ver.edit_session_id,
        source_generation_id=ver.source_generation_id,
        parent_version=ver.parent_version,
        version=ver.version,
        changed_files=ver.changed_files,
        diff_summary=ver.diff_summary,
        source_checksum=ver.source_checksum,
        artifact_id=ver.artifact_id,
        is_active=ver.is_active,
        metadata=ver.version_metadata,
        created_at=ver.created_at,
    )


# ── Phase 6.5 Preview Endpoints ───────────────────────────────────────────────

@router.post(
    "/projects/{project_id}/previews",
    response_model=WebsitePreviewResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an isolated live website preview instance",
)
async def create_preview(
    project_id: uuid.UUID,
    payload: WebsitePreviewCreateRequest = WebsitePreviewCreateRequest(),
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsitePreviewResponse:
    """Creates an isolated preview instance for a completed code generation."""
    verify_owner_access(owner_email)
    try:
        preview = await WebsitePreviewService.create_preview(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
            code_generation_id=payload.code_generation_id,
        )
        return _serialize_preview(preview)
    except PreviewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PreviewOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except PreviewIneligibleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/projects/{project_id}/previews",
    response_model=WebsitePreviewListResponse,
    summary="List all preview instances for a project",
)
async def list_previews(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsitePreviewListResponse:
    """Lists preview instances belonging to the given project."""
    verify_owner_access(owner_email)
    try:
        previews = await WebsitePreviewService.list_previews_for_project(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
        )
        return WebsitePreviewListResponse(
            previews=[_serialize_preview(p) for p in previews],
            total_count=len(previews),
        )
    except PreviewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PreviewOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/previews/{preview_id}",
    response_model=WebsitePreviewResponse,
    summary="Retrieve details for a preview instance",
)
async def get_preview(
    preview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsitePreviewResponse:
    """Retrieves a preview instance by ID."""
    verify_owner_access(owner_email)
    try:
        preview = await WebsitePreviewService.get_preview(
            db=db,
            preview_id=preview_id,
            owner_id=owner_email,
        )
        return _serialize_preview(preview)
    except PreviewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PreviewOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/previews/{preview_id}/start",
    response_model=WebsitePreviewResponse,
    summary="Start an isolated preview server",
)
async def start_preview(
    preview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsitePreviewResponse:
    """Starts a preview instance and initializes its TTL."""
    verify_owner_access(owner_email)
    try:
        preview = await WebsitePreviewService.start_preview(
            db=db,
            preview_id=preview_id,
            owner_id=owner_email,
        )
        return _serialize_preview(preview)
    except PreviewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PreviewOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/previews/{preview_id}/stop",
    response_model=WebsitePreviewResponse,
    summary="Stop an isolated preview server",
)
async def stop_preview(
    preview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsitePreviewResponse:
    """Stops an active preview instance."""
    verify_owner_access(owner_email)
    try:
        preview = await WebsitePreviewService.stop_preview(
            db=db,
            preview_id=preview_id,
            owner_id=owner_email,
        )
        return _serialize_preview(preview)
    except PreviewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PreviewOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.post(
    "/previews/{preview_id}/restart",
    response_model=WebsitePreviewResponse,
    summary="Restart an isolated preview server",
)
async def restart_preview(
    preview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsitePreviewResponse:
    """Restarts a preview instance and resets runtime timers."""
    verify_owner_access(owner_email)
    try:
        preview = await WebsitePreviewService.restart_preview(
            db=db,
            preview_id=preview_id,
            owner_id=owner_email,
        )
        return _serialize_preview(preview)
    except PreviewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PreviewOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/previews/{preview_id}/status",
    response_model=WebsitePreviewStatusResponse,
    summary="Get real-time operational status for a preview instance",
)
async def get_preview_status(
    preview_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsitePreviewStatusResponse:
    """Calculates runtime uptime and returns status."""
    verify_owner_access(owner_email)
    try:
        return await WebsitePreviewService.get_preview_status(
            db=db,
            preview_id=preview_id,
            owner_id=owner_email,
        )
    except PreviewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PreviewOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/previews/{preview_id}/render",
    response_class=HTMLResponse,
    summary="Render isolated preview HTML safely in a container/iframe",
)
async def render_preview(
    preview_id: uuid.UUID,
    token: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> HTMLResponse:
    """
    Renders the sandboxed website preview HTML.
    Enforces owner authorization and strict Content-Security-Policy headers.
    """
    verify_owner_access(owner_email)
    try:
        preview = await WebsitePreviewService.get_preview(
            db=db,
            preview_id=preview_id,
            owner_id=owner_email,
        )
        html_body = WebsitePreviewService.render_preview_html(preview)
        response = HTMLResponse(content=html_body, status_code=200)
        # Strict frame ancestor and content security policy
        response.headers["Content-Security-Policy"] = (
            "default-src 'self' 'unsafe-inline' data:; frame-ancestors 'self' http://localhost:3000 http://localhost:3001;"
        )
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    except PreviewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PreviewOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# ── Phase 6.5 Iterative Editing Endpoints ─────────────────────────────────────

@router.post(
    "/projects/{project_id}/edits",
    response_model=WebsiteEditDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Initiate and apply an AI-assisted iterative edit to the website",
)
async def create_edit(
    project_id: uuid.UUID,
    payload: WebsiteEditCreateRequest,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteEditDetailResponse:
    """Executes a targeted, minimal iterative edit against the active website version."""
    verify_owner_access(owner_email)
    try:
        session, version = await WebsiteEditingService.initiate_and_apply_edit(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
            request_payload=payload,
        )
        return WebsiteEditDetailResponse(
            edit=_serialize_edit(session),
            changed_files=version.changed_files,
            diff_summary=version.diff_summary,
            version_created=version.version,
            new_version_id=version.id,
        )
    except EditNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except EditOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except StaleBaseVersionConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except ConcurrentEditConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except EditValidationFailureError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except EditIneligibleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/projects/{project_id}/edits",
    response_model=WebsiteEditListResponse,
    summary="List all edit sessions for a project",
)
async def list_edits(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteEditListResponse:
    """Lists iterative edit sessions belonging to the project."""
    verify_owner_access(owner_email)
    try:
        edits = await WebsiteEditingService.list_edits_for_project(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
        )
        return WebsiteEditListResponse(
            edits=[_serialize_edit(e) for e in edits],
            total_count=len(edits),
        )
    except EditNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except EditOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/edits/{edit_id}",
    response_model=WebsiteEditDetailResponse,
    summary="Retrieve details for an edit session",
)
async def get_edit(
    edit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteEditDetailResponse:
    """Retrieves an edit session by ID."""
    verify_owner_access(owner_email)
    edit = await db.get(WebsiteEditSession, edit_id)
    if not edit:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Edit session '{edit_id}' not found.")
    if edit.owner_id != owner_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access to edit session.")

    return WebsiteEditDetailResponse(
        edit=_serialize_edit(edit),
        changed_files=edit.edit_metadata.get("changed_files", []),
        diff_summary=edit.edit_metadata.get("diff_summary"),
        version_created=edit.edit_metadata.get("version_created"),
        new_version_id=uuid.UUID(edit.edit_metadata["version_id"]) if edit.edit_metadata.get("version_id") else None,
    )


@router.post(
    "/edits/{edit_id}/cancel",
    response_model=WebsiteEditResponse,
    summary="Cancel an active edit session",
)
async def cancel_edit(
    edit_id: uuid.UUID,
    payload: WebsiteEditCancelRequest = WebsiteEditCancelRequest(),
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteEditResponse:
    """Cancels an active or pending edit session."""
    verify_owner_access(owner_email)
    try:
        edit = await WebsiteEditingService.cancel_edit(
            db=db,
            edit_id=edit_id,
            owner_id=owner_email,
            reason=payload.reason,
        )
        return _serialize_edit(edit)
    except EditNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except EditOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except EditIneligibleError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/edits/{edit_id}/apply",
    response_model=WebsiteEditDetailResponse,
    summary="Confirm or re-apply an edit session",
)
async def apply_edit(
    edit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteEditDetailResponse:
    """Returns applied edit detail."""
    return await get_edit(edit_id=edit_id, db=db, owner_email=owner_email)


# ── Phase 6.5 Versioning & Rollback Endpoints ─────────────────────────────────

@router.get(
    "/projects/{project_id}/versions",
    response_model=WebsiteVersionListResponse,
    summary="List all immutable website versions for a project",
)
async def list_versions(
    project_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteVersionListResponse:
    """Lists all version records and identifies the currently active version."""
    verify_owner_access(owner_email)
    try:
        versions = await WebsiteEditingService.list_versions_for_project(
            db=db,
            project_id=project_id,
            owner_id=owner_email,
        )
        active_ver = await WebsiteEditingService.get_active_version(db, project_id)
        current_version_num = active_ver.version if active_ver else (versions[0].version if versions else 1)

        return WebsiteVersionListResponse(
            versions=[_serialize_version(v) for v in versions],
            current_version=current_version_num,
            total_count=len(versions),
        )
    except EditNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except EditOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


@router.get(
    "/versions/{version_id}",
    response_model=WebsiteEditVersionResponse,
    summary="Retrieve details for a specific website version",
)
async def get_version(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteEditVersionResponse:
    """Retrieves an immutable version record by ID."""
    verify_owner_access(owner_email)
    ver = await db.get(WebsiteEditVersion, version_id)
    if not ver:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version '{version_id}' not found.")
    if ver.owner_id != owner_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Unauthorized access to version.")
    return _serialize_version(ver)


@router.post(
    "/versions/{version_id}/rollback",
    response_model=WebsiteVersionRollbackResponse,
    summary="Execute a non-destructive rollback to a previous version",
)
async def rollback_version(
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    owner_email: str = Depends(require_owner),
) -> WebsiteVersionRollbackResponse:
    """
    Rolls back the active website codebase to the target version.
    Crucial: Creates a new sequential version without altering or deleting prior history.
    """
    verify_owner_access(owner_email)
    try:
        target_ver, new_ver, record = await WebsiteEditingService.rollback_to_version(
            db=db,
            version_id=version_id,
            owner_id=owner_email,
        )
        return WebsiteVersionRollbackResponse(
            message=f"Successfully rolled back to version v{target_ver}. New active release is v{new_ver}.",
            rolled_back_to_version=target_ver,
            new_version=new_ver,
            version_record=_serialize_version(record),
        )
    except EditNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except EditOwnershipError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
