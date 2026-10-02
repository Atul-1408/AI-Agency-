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
    InboundMessage,
)
from routers.auth import require_owner
from schemas import PaginatedResponse
from schemas.follow_up import (
    DetectRepliesRequest,
    DetectRepliesResponse,
    FollowUpDraftGenerateResponse,
    FollowUpEligibilityCheckResponse,
    FollowUpSequenceCreateRequest,
    FollowUpSequenceResponse,
    FollowUpSequenceStopRequest,
    FollowUpSendResponse,
    FollowUpStepResponse,
    InboundMessageResponse,
    ReplyDetectedRequest,
)
from services.follow_up_dispatch_service import (
    FollowUpDispatchEligibilityError,
    FollowUpDispatchGmailError,
    FollowUpDispatchIdempotentError,
    FollowUpDispatchReplyDetectedError,
    FollowUpDispatchSafetyError,
    FollowUpDispatchSequenceNotFoundError,
    FollowUpDispatchService,
    FollowUpDispatchStepNotFoundError,
    FollowUpDispatchDraftNotFoundError,
)
from services.follow_up_draft_service import (
    FollowUpDraftEligibilityError,
    FollowUpDraftService,
    ReplyDetectedError,
    StepNotFoundError,
)
from services.follow_up_eligibility_service import FollowUpEligibilityService
from services.follow_up_service import (
    DuplicateActiveSequenceError,
    FollowUpService,
    InvalidMessageError,
    InvalidStateTransitionError,
    SequenceNotFoundError,
)
from services.gmail_reply_service import (
    GmailReplyAuthError,
    GmailReplyError,
    GmailReplyMalformedError,
    GmailReplyNetworkError,
    GmailReplyPermissionError,
    GmailReplyRateLimitError,
    GmailReplyServerError,
    GmailReplyTimeoutError,
)
from services.reply_detection_service import (
    DisconnectedGmailAccountError,
    ReplyDetectionService,
)

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


@router.post("/detect-replies", response_model=DetectRepliesResponse)
async def detect_replies(
    payload: Optional[DetectRepliesRequest] = None,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> DetectRepliesResponse:
    """
    Manually trigger detection of prospect replies from Gmail thread metadata.
    
    Security & Governance:
    - Protected by owner authentication and IDOR checks.
    - Uses only the authenticated owner's connected Gmail account.
    - Inspects only threads of known active/paused outreach sequences.
    - Fails closed on any authentication or infrastructure error.
    - Never exposes OAuth tokens or full email bodies.
    """
    verify_owner_access(owner_email)

    sequence_id = payload.sequence_id if payload else None
    limit = payload.limit if payload else 50

    reply_service = ReplyDetectionService()

    try:
        summary = await reply_service.detect_replies_for_owner(
            db=db,
            owner_id=owner_email,
            sequence_id=sequence_id,
            limit=limit,
        )
        return DetectRepliesResponse(
            checked=summary.checked,
            replies_detected=summary.replies_detected,
            sequences_stopped=summary.sequences_stopped,
            duplicates_ignored=summary.duplicates_ignored,
        )
    except DisconnectedGmailAccountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except GmailReplyAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )
    except GmailReplyPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except GmailReplyRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        )
    except GmailReplyTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        )
    except (GmailReplyServerError, GmailReplyNetworkError, GmailReplyMalformedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    except Exception as exc:
        log.error("Unexpected error during reply detection", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred during reply detection.",
        )


@router.get("/inbound-messages", response_model=PaginatedResponse)
async def list_inbound_messages(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    lead_id: Optional[uuid.UUID] = Query(None, description="Filter by lead ID"),
    sequence_id: Optional[uuid.UUID] = Query(None, description="Filter by sequence ID"),
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """List detected inbound prospect messages with safe metadata and pagination."""
    verify_owner_access(owner_email)

    query = select(InboundMessage)
    count_query = select(func.count(InboundMessage.id))

    if lead_id:
        query = query.where(InboundMessage.matched_lead_id == lead_id)
        count_query = count_query.where(InboundMessage.matched_lead_id == lead_id)

    if sequence_id:
        query = query.where(InboundMessage.matched_sequence_id == sequence_id)
        count_query = count_query.where(InboundMessage.matched_sequence_id == sequence_id)

    total = await db.scalar(count_query) or 0

    offset = (page - 1) * page_size
    query = query.order_by(InboundMessage.detected_at.desc()).offset(offset).limit(page_size)

    messages = (await db.scalars(query)).all()

    return PaginatedResponse(
        items=[InboundMessageResponse.model_validate(m) for m in messages],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/sequences/{sequence_id}/steps/{step_id}/generate-draft",
    response_model=FollowUpDraftGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_follow_up_draft(
    sequence_id: uuid.UUID,
    step_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> FollowUpDraftGenerateResponse:
    """
    Generate a factual personalized follow-up draft for an eligible sequence step.
    The draft is persisted strictly with status = PENDING_APPROVAL for Gate 2 human review.
    
    Security & Governance:
    - Requires owner authentication and IDOR verification.
    - Evaluates strict sequence/step eligibility.
    - Fresh reply check: aborts and terminates sequence if prospect already replied.
    - Idempotent: returns existing draft if one was already generated.
    - Concurrency-safe: database unique constraint prevents duplicate drafts.
    - Send-free: never executes email dispatch or consumes send quota.
    """
    verify_owner_access(owner_email)

    draft_service = FollowUpDraftService()

    try:
        draft, is_existing = await draft_service.generate_draft_for_step(
            db=db,
            sequence_id=sequence_id,
            step_id=step_id,
            owner_id=owner_email,
        )
        return FollowUpDraftGenerateResponse(
            draft_id=draft.id,
            sequence_id=sequence_id,
            step_id=step_id,
            status=draft.status.value,
            subject=draft.subject,
            recipient_email=draft.recipient_email,
            is_existing=is_existing,
        )
    except SequenceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except StepNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except ReplyDetectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )
    except FollowUpDraftEligibilityError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        log.error("Unexpected error generating follow-up draft", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error generating follow-up draft.",
        )


# ── Stage 4.7 — Follow-up Send Authorization & Dispatch ──────────────────────

@router.post(
    "/sequences/{sequence_id}/steps/{step_id}/send",
    response_model=FollowUpSendResponse,
    status_code=status.HTTP_200_OK,
)
async def send_follow_up_step(
    sequence_id: uuid.UUID,
    step_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> FollowUpSendResponse:
    """
    Dispatch a single approved follow-up draft for a specific sequence step.

    COMPLETE PRE-SEND ORDER:
    1. Owner authentication and IDOR verification.
    2. Sequence and step loaded with row locking (concurrency-safe).
    3. Idempotency: blocked if step is already SENT.
    4. Eligibility: sequence must be ACTIVE, step PENDING or READY,
       original message SENT, lead not disqualified, Gmail healthy,
       not suppressed, circuit breaker permits.
    5. Draft verification: attached draft must be APPROVED (Gate 2).
    6. Fresh database reply check: dispatch blocked and sequence stopped
       if a reply is already recorded for the thread.
    7. SafetyController full 12-point authorization (quotas, pacing,
       suppression, MX verification, Gmail health, circuit breaker).
    8. Gmail account connectivity verification.
    9. GmailDispatchService sends exactly ONE message.
    10. OutreachMessage + SendAttempt recorded.
    11. FollowUpStep → SENT, sequence advances or COMPLETES.
    12. Immutable audit trail in agent_runs.

    Fails closed on any safety, eligibility, or infrastructure failure.
    Never sends without Gate 2 approval.
    Never bypasses SafetyController.
    """
    verify_owner_access(owner_email)
    dispatch_service = FollowUpDispatchService()

    try:
        result = await dispatch_service.dispatch_follow_up_step(
            db=db,
            sequence_id=sequence_id,
            step_id=step_id,
            owner_id=owner_email,
        )
        await db.commit()
        return FollowUpSendResponse(
            success=True,
            outreach_message_id=result.outreach_message_id,
            send_attempt_id=result.send_attempt_id,
            gmail_message_id=result.gmail_message_id,
            gmail_thread_id=result.gmail_thread_id,
            sent_at=result.sent_at,
            recipient_email=result.recipient_email,
            subject=result.subject,
            sequence_id=result.sequence_id,
            step_id=result.step_id,
            step_number=result.step_number,
            sequence_completed=result.sequence_completed,
            status="sent",
        )
    except FollowUpDispatchSequenceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except FollowUpDispatchStepNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except FollowUpDispatchDraftNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except FollowUpDispatchIdempotentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except FollowUpDispatchReplyDetectedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except FollowUpDispatchEligibilityError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except FollowUpDispatchSafetyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except FollowUpDispatchGmailError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    except Exception as exc:
        log.error(
            "Unexpected error during follow-up dispatch",
            sequence_id=str(sequence_id),
            step_id=str(step_id),
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unexpected error occurred during follow-up dispatch.",
        )
