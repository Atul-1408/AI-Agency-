"""
Follow-up Sequence Owner API Router.

Provides authenticated endpoints for owner management of follow-up sequences:
- Instantiate follow-up sequence
- List sequences with filtering
- Retrieve sequence detail with ordered steps
- Pause / resume / stop controls
- Reply detection callback/webhook boundary
- Eligibility check query

Enforces strict owner authentication and IDOR access control on every endpoint.
"""
from __future__ import annotations

from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from core.config import settings
from core.database import get_db
from models.follow_up import (
    FollowUpSequence,
    FollowUpSequenceStatus,
    FollowUpStep,
    FollowUpStopReason,
)
from routers.auth import require_owner
from schemas import PaginatedResponse
from schemas.follow_up import (
    FollowUpEligibilityCheckResponse,
    FollowUpSequenceCreateRequest,
    FollowUpSequenceResponse,
    FollowUpSequenceStopRequest,
    FollowUpStepResponse,
    ReplyDetectedRequest,
)
from services.follow_up_eligibility_service import FollowUpEligibilityService
from services.follow_up_service import (
    DuplicateActiveSequenceError,
    FollowUpService,
    InvalidMessageError,
    InvalidStateTransitionError,
    SequenceNotFoundError,
)
from services.reply_detection_service import ReplyDetectionService

router = APIRouter()
log = structlog.get_logger(__name__)


def verify_owner_access(owner_email: str) -> None:
    """
    IDOR Protection: Verify authenticated user matches configured agency owner.
    Prevents unauthorized or foreign owners from accessing or modifying follow-up sequences.
    """
    if settings.OWNER_EMAIL and owner_email.lower().strip() != settings.OWNER_EMAIL.lower().strip():
        log.warning("IDOR/unauthorized owner access attempted on follow-up API", owner=owner_email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Authenticated user is not authorized to access or modify this agency's follow-up resources",
        )


@router.post("/sequences", response_model=FollowUpSequenceResponse, status_code=status.HTTP_201_CREATED)
async def create_sequence(
    payload: FollowUpSequenceCreateRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> FollowUpSequenceResponse:
    """
    Create a new follow-up sequence anchored to a sent outreach message.
    """
    verify_owner_access(owner_email)
    service = FollowUpService()

    try:
        seq = await service.create_sequence(
            db=db,
            original_message_id=payload.original_message_id,
            cadence=payload.cadence,
            owner_id=owner_email,
        )
    except InvalidMessageError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except DuplicateActiveSequenceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # Load child steps
    steps = (
        await db.scalars(
            select(FollowUpStep)
            .where(FollowUpStep.sequence_id == seq.id)
            .order_by(FollowUpStep.step_number.asc())
        )
    ).all()

    return FollowUpSequenceResponse(
        id=seq.id,
        lead_id=seq.lead_id,
        outreach_draft_id=seq.outreach_draft_id,
        original_message_id=seq.original_message_id,
        status=seq.status,
        current_step=seq.current_step,
        max_steps=seq.max_steps,
        next_action_at=seq.next_action_at,
        stopped_at=seq.stopped_at,
        stop_reason=seq.stop_reason,
        created_at=seq.created_at,
        updated_at=seq.updated_at,
        steps=[FollowUpStepResponse.model_validate(s) for s in steps],
    )


@router.get("/sequences", response_model=PaginatedResponse)
async def list_sequences(
    status_filter: Optional[FollowUpSequenceStatus] = Query(None, alias="status", description="Filter by status"),
    lead_id: Optional[uuid.UUID] = Query(None, description="Filter by lead ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """
    List follow-up sequences with filtering and pagination.
    """
    verify_owner_access(owner_email)

    query = select(FollowUpSequence)
    if status_filter:
        query = query.where(FollowUpSequence.status == status_filter)
    if lead_id:
        query = query.where(FollowUpSequence.lead_id == lead_id)

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.scalar(count_query)) or 0

    query = (
        query.order_by(FollowUpSequence.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    sequences = (await db.scalars(query)).all()

    items = []
    for seq in sequences:
        steps = (
            await db.scalars(
                select(FollowUpStep)
                .where(FollowUpStep.sequence_id == seq.id)
                .order_by(FollowUpStep.step_number.asc())
            )
        ).all()
        items.append(
            FollowUpSequenceResponse(
                id=seq.id,
                lead_id=seq.lead_id,
                outreach_draft_id=seq.outreach_draft_id,
                original_message_id=seq.original_message_id,
                status=seq.status,
                current_step=seq.current_step,
                max_steps=seq.max_steps,
                next_action_at=seq.next_action_at,
                stopped_at=seq.stopped_at,
                stop_reason=seq.stop_reason,
                created_at=seq.created_at,
                updated_at=seq.updated_at,
                steps=[FollowUpStepResponse.model_validate(s) for s in steps],
            ).model_dump()
        )

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/sequences/{sequence_id}", response_model=FollowUpSequenceResponse)
async def get_sequence(
    sequence_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> FollowUpSequenceResponse:
    """
    Retrieve single sequence detail with its ordered steps.
    """
    verify_owner_access(owner_email)

    seq = await db.scalar(select(FollowUpSequence).where(FollowUpSequence.id == sequence_id))
    if not seq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Follow-up sequence {sequence_id} does not exist.",
        )

    steps = (
        await db.scalars(
            select(FollowUpStep)
            .where(FollowUpStep.sequence_id == seq.id)
            .order_by(FollowUpStep.step_number.asc())
        )
    ).all()

    return FollowUpSequenceResponse(
        id=seq.id,
        lead_id=seq.lead_id,
        outreach_draft_id=seq.outreach_draft_id,
        original_message_id=seq.original_message_id,
        status=seq.status,
        current_step=seq.current_step,
        max_steps=seq.max_steps,
        next_action_at=seq.next_action_at,
        stopped_at=seq.stopped_at,
        stop_reason=seq.stop_reason,
        created_at=seq.created_at,
        updated_at=seq.updated_at,
        steps=[FollowUpStepResponse.model_validate(s) for s in steps],
    )


@router.post("/sequences/{sequence_id}/pause", response_model=FollowUpSequenceResponse)
async def pause_sequence(
    sequence_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> FollowUpSequenceResponse:
    """Pause an ACTIVE follow-up sequence."""
    verify_owner_access(owner_email)
    service = FollowUpService()

    try:
        seq = await service.pause_sequence(db=db, sequence_id=sequence_id, owner_id=owner_email)
    except SequenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    steps = (
        await db.scalars(
            select(FollowUpStep)
            .where(FollowUpStep.sequence_id == seq.id)
            .order_by(FollowUpStep.step_number.asc())
        )
    ).all()

    return FollowUpSequenceResponse(
        id=seq.id,
        lead_id=seq.lead_id,
        outreach_draft_id=seq.outreach_draft_id,
        original_message_id=seq.original_message_id,
        status=seq.status,
        current_step=seq.current_step,
        max_steps=seq.max_steps,
        next_action_at=seq.next_action_at,
        stopped_at=seq.stopped_at,
        stop_reason=seq.stop_reason,
        created_at=seq.created_at,
        updated_at=seq.updated_at,
        steps=[FollowUpStepResponse.model_validate(s) for s in steps],
    )


@router.post("/sequences/{sequence_id}/resume", response_model=FollowUpSequenceResponse)
async def resume_sequence(
    sequence_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> FollowUpSequenceResponse:
    """Resume a PAUSED follow-up sequence back to ACTIVE."""
    verify_owner_access(owner_email)
    service = FollowUpService()

    try:
        seq = await service.resume_sequence(db=db, sequence_id=sequence_id, owner_id=owner_email)
    except SequenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    steps = (
        await db.scalars(
            select(FollowUpStep)
            .where(FollowUpStep.sequence_id == seq.id)
            .order_by(FollowUpStep.step_number.asc())
        )
    ).all()

    return FollowUpSequenceResponse(
        id=seq.id,
        lead_id=seq.lead_id,
        outreach_draft_id=seq.outreach_draft_id,
        original_message_id=seq.original_message_id,
        status=seq.status,
        current_step=seq.current_step,
        max_steps=seq.max_steps,
        next_action_at=seq.next_action_at,
        stopped_at=seq.stopped_at,
        stop_reason=seq.stop_reason,
        created_at=seq.created_at,
        updated_at=seq.updated_at,
        steps=[FollowUpStepResponse.model_validate(s) for s in steps],
    )


@router.post("/sequences/{sequence_id}/stop", response_model=FollowUpSequenceResponse)
async def stop_sequence(
    sequence_id: uuid.UUID,
    payload: FollowUpSequenceStopRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> FollowUpSequenceResponse:
    """Permanently stop a sequence and cancel pending steps."""
    verify_owner_access(owner_email)
    service = FollowUpService()

    try:
        seq = await service.stop_sequence(
            db=db,
            sequence_id=sequence_id,
            reason=payload.reason or FollowUpStopReason.OWNER_STOPPED,
            notes=payload.notes,
            owner_id=owner_email,
        )
    except SequenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except InvalidStateTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    steps = (
        await db.scalars(
            select(FollowUpStep)
            .where(FollowUpStep.sequence_id == seq.id)
            .order_by(FollowUpStep.step_number.asc())
        )
    ).all()

    return FollowUpSequenceResponse(
        id=seq.id,
        lead_id=seq.lead_id,
        outreach_draft_id=seq.outreach_draft_id,
        original_message_id=seq.original_message_id,
        status=seq.status,
        current_step=seq.current_step,
        max_steps=seq.max_steps,
        next_action_at=seq.next_action_at,
        stopped_at=seq.stopped_at,
        stop_reason=seq.stop_reason,
        created_at=seq.created_at,
        updated_at=seq.updated_at,
        steps=[FollowUpStepResponse.model_validate(s) for s in steps],
    )


@router.post("/sequences/{sequence_id}/reply-detected", response_model=FollowUpSequenceResponse)
async def record_reply_detected(
    sequence_id: uuid.UUID,
    payload: ReplyDetectedRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> FollowUpSequenceResponse:
    """Record a verified reply detection on a sequence, stopping it immediately."""
    verify_owner_access(owner_email)
    reply_service = ReplyDetectionService()

    try:
        seq = await reply_service.handle_reply_detected(
            db=db,
            sequence_id=sequence_id,
            detected_at=payload.detected_at,
            gmail_message_id=payload.gmail_message_id,
            snippet=payload.snippet,
            owner_id=owner_email,
        )
    except SequenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    steps = (
        await db.scalars(
            select(FollowUpStep)
            .where(FollowUpStep.sequence_id == seq.id)
            .order_by(FollowUpStep.step_number.asc())
        )
    ).all()

    return FollowUpSequenceResponse(
        id=seq.id,
        lead_id=seq.lead_id,
        outreach_draft_id=seq.outreach_draft_id,
        original_message_id=seq.original_message_id,
        status=seq.status,
        current_step=seq.current_step,
        max_steps=seq.max_steps,
        next_action_at=seq.next_action_at,
        stopped_at=seq.stopped_at,
        stop_reason=seq.stop_reason,
        created_at=seq.created_at,
        updated_at=seq.updated_at,
        steps=[FollowUpStepResponse.model_validate(s) for s in steps],
    )


@router.get("/sequences/{sequence_id}/eligibility", response_model=FollowUpEligibilityCheckResponse)
async def check_sequence_eligibility(
    sequence_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> FollowUpEligibilityCheckResponse:
    """Evaluate whether a follow-up sequence is eligible to proceed with its next step."""
    verify_owner_access(owner_email)

    seq = await db.scalar(select(FollowUpSequence).where(FollowUpSequence.id == sequence_id))
    if not seq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Follow-up sequence {sequence_id} does not exist.",
        )

    current_step = await db.scalar(
        select(FollowUpStep).where(
            FollowUpStep.sequence_id == seq.id,
            FollowUpStep.step_number == seq.current_step,
        )
    )

    eligibility_service = FollowUpEligibilityService()
    result = await eligibility_service.evaluate_sequence_eligibility(
        db=db, sequence=seq, step=current_step
    )

    return FollowUpEligibilityCheckResponse(
        eligible=result.eligible,
        reason=result.reason,
        checks_passed=result.checks_passed,
    )
