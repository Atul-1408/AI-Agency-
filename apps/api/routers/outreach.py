"""
Outreach Router — Phase 3 Stage 3.4.

Implements Gate 2 Human Approval API:
  - GET   /api/v1/outreach/drafts             — List & filter drafts
  - GET   /api/v1/outreach/drafts/{draft_id}  — View draft detail with lead research evidence
  - POST  /api/v1/outreach/drafts/{draft_id}/approve — Approve draft for sending (Gate 2)
  - POST  /api/v1/outreach/drafts/{draft_id}/reject  — Reject draft with mandatory reason
  - PATCH /api/v1/outreach/drafts/{draft_id}         — Edit subject/body (PENDING_APPROVAL only)
  - POST  /api/v1/outreach/drafts/{draft_id}/reset   — Return approved/rejected draft to PENDING_APPROVAL
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from models import (
    AgentRun,
    AgentRunStatus,
    GmailAccount,
    GmailConnectionStatus,
    OutreachDraft,
    OutreachDraftStatus,
    OutreachMessage,
    OutreachMessageStatus,
    SendAttempt,
    SendAttemptResult,
)
from routers.auth import require_owner
from schemas import PaginatedResponse
from schemas.outreach import (
    GmailDispatchResponse,
    OutreachDraftRejectRequest,
    OutreachDraftResponse,
    OutreachDraftUpdateRequest,
)
from services.gmail_dispatch_service import (
    GmailDispatchError,
    GmailDispatchService,
)
from services.outreach_service import (
    DraftNotFoundError,
    InvalidStateTransitionError,
    OutreachService,
)
from services.safety_controller import SafetyController

router = APIRouter()
log = structlog.get_logger(__name__)


def verify_owner_access(owner_email: str) -> None:
    """
    IDOR Protection: Verify authenticated user matches configured agency owner.
    Prevents unauthorized or foreign owners from accessing or modifying outreach resources.
    """
    if settings.OWNER_EMAIL and owner_email.lower().strip() != settings.OWNER_EMAIL.lower().strip():
        log.warning("IDOR/unauthorized owner access attempted", owner=owner_email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Authenticated user is not authorized to access or modify this agency's outreach resources",
        )


@router.get("/drafts", response_model=PaginatedResponse)
async def list_drafts(
    status_filter: Optional[OutreachDraftStatus] = Query(None, alias="status", description="Filter by draft status"),
    lead_id: Optional[uuid.UUID] = Query(None, description="Filter by lead ID"),
    recipient_email: Optional[str] = Query(None, description="Filter by recipient email"),
    created_after: Optional[datetime] = Query(None, description="Filter drafts created on or after"),
    created_before: Optional[datetime] = Query(None, description="Filter drafts created on or before"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """
    List outreach drafts with filtering and pagination.
    Requires authenticated owner.
    """
    verify_owner_access(owner_email)
    service = OutreachService(db)

    total, items = await service.list_drafts(
        status=status_filter,
        lead_id=lead_id,
        recipient_email=recipient_email,
        created_after=created_after,
        created_before=created_before,
        page=page,
        page_size=page_size,
    )

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get("/drafts/{draft_id}", response_model=OutreachDraftResponse)
async def get_draft(
    draft_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> OutreachDraftResponse:
    """
    Retrieve full outreach draft details including company name, domain,
    evidence/factual observations from technical audit findings, and approval metadata.
    """
    verify_owner_access(owner_email)
    service = OutreachService(db)

    try:
        return await service.get_draft_detail(draft_id)
    except DraftNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/drafts/{draft_id}/approve", response_model=OutreachDraftResponse)
async def approve_draft(
    draft_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> OutreachDraftResponse:
    """
    Gate 2 Owner Approval:
    Owner approves outreach draft for sending.
    Requires:
    - Authenticated owner
    - Draft exists in PENDING_APPROVAL status
    - Associated lead is APPROVED (Gate 1)
    - Recipient email is MX_VERIFIED
    Transitions draft to APPROVED and records immutable audit log.
    """
    verify_owner_access(owner_email)
    service = OutreachService(db)

    try:
        response = await service.approve_draft(draft_id, owner_email)
        await db.commit()
        return response
    except DraftNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidStateTransitionError as e:
        await db.commit()  # Preserve recorded audit log of failed attempt
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/drafts/{draft_id}/reject", response_model=OutreachDraftResponse)
async def reject_draft(
    draft_id: uuid.UUID,
    payload: OutreachDraftRejectRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> OutreachDraftResponse:
    """
    Gate 2 Owner Rejection:
    Owner rejects outreach draft.
    Requires:
    - Authenticated owner
    - Draft exists in PENDING_APPROVAL status
    - Non-empty rejection reason
    Transitions draft to REJECTED and records immutable audit log.
    """
    verify_owner_access(owner_email)
    service = OutreachService(db)

    try:
        response = await service.reject_draft(draft_id, owner_email, payload.reason)
        await db.commit()
        return response
    except DraftNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidStateTransitionError as e:
        await db.commit()  # Preserve recorded audit log of failed attempt
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


@router.patch("/drafts/{draft_id}", response_model=OutreachDraftResponse)
async def edit_draft(
    draft_id: uuid.UUID,
    payload: OutreachDraftUpdateRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> OutreachDraftResponse:
    """
    Edit draft subject or body.
    CRITICAL POLICY:
    - Permitted ONLY when draft is PENDING_APPROVAL.
    - Edits on APPROVED or REJECTED drafts are strictly forbidden.
    - An approved draft cannot be modified without being returned to PENDING_APPROVAL.
    """
    verify_owner_access(owner_email)
    service = OutreachService(db)

    try:
        response = await service.edit_draft(
            draft_id,
            owner_email,
            subject=payload.subject,
            body_text=payload.body_text,
            body_html=payload.body_html,
        )
        await db.commit()
        return response
    except DraftNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidStateTransitionError as e:
        await db.commit()  # Preserve recorded audit log of failed attempt
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/drafts/{draft_id}/reset", response_model=OutreachDraftResponse)
async def reset_draft(
    draft_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> OutreachDraftResponse:
    """
    Return an approved or rejected draft back to PENDING_APPROVAL.
    Ensures that if an approved draft ever needs modification, it returns
    to PENDING_APPROVAL and requires fresh Gate 2 approval.
    """
    verify_owner_access(owner_email)
    service = OutreachService(db)

    try:
        response = await service.reset_draft_to_pending(draft_id, owner_email)
        await db.commit()
        return response
    except DraftNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except InvalidStateTransitionError as e:
        await db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


async def log_dispatch_audit(
    db: AsyncSession,
    action: str,
    owner_email: str,
    status: AgentRunStatus,
    input_data: Optional[Dict[str, Any]] = None,
    output_data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> AgentRun:
    """
    Record an immutable audit entry in agent_runs for outreach dispatch lifecycle events.
    Strictly sanitizes all payloads to prevent any secret or token leakage.
    """
    now = datetime.now(timezone.utc)
    forbidden_keys = {
        "token", "refresh_token", "access_token", "client_secret",
        "code", "authorization_code", "encrypted_refresh_token", "key"
    }

    def _sanitize(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not data:
            return {}
        return {k: v for k, v in data.items() if k.lower() not in forbidden_keys}

    run = AgentRun(
        agent_name="gmail_dispatch",
        status=status,
        input_data={
            "action": action,
            "owner": owner_email,
            **_sanitize(input_data),
        },
        output_data=_sanitize(output_data),
        error_message=error_message,
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    await db.flush()
    return run


# ── Single Manual Send (Phase 4 Stage 4.3) ───────────────────────────────────

@router.post("/drafts/{draft_id}/send", response_model=GmailDispatchResponse)
async def send_draft(
    draft_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> GmailDispatchResponse:
    """
    Controlled Single-Email Manual Dispatch Path.
    
    PRE-SEND SAFETY ORDER:
    1. Authenticate & authorize agency owner.
    2. Load draft with row locking to prevent race conditions.
    3. Idempotency check: block duplicate send if draft is already SENT.
    4. Verify draft status == APPROVED (Gate 2 human approval).
    5. Run full 12-point SafetyController authorization (quotas, pacing, suppression, MX, health).
    6. Verify owner's Gmail account is CONNECTED.
    7. Send exactly ONE message via GmailDispatchService.
    8. Record OutreachMessage and SendAttempt.
    9. Complete immutable audit trail.
    """
    verify_owner_access(owner_email)

    # 1. Audit dispatch requested
    await log_dispatch_audit(
        db=db,
        action="dispatch_requested",
        owner_email=owner_email,
        status=AgentRunStatus.PENDING,
        input_data={"draft_id": str(draft_id)},
    )

    # 2. Load draft with concurrency protection
    stmt = select(OutreachDraft).where(OutreachDraft.id == draft_id).with_for_update()
    draft = await db.scalar(stmt)
    if not draft:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outreach draft {draft_id} does not exist.",
        )

    # 3. Idempotency & Duplicate Send Protection
    if draft.status == OutreachDraftStatus.SENT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Outreach draft has already been sent.",
        )

    existing_sent_message = await db.scalar(
        select(OutreachMessage).where(
            OutreachMessage.draft_id == draft.id,
            OutreachMessage.status == OutreachMessageStatus.SENT,
        )
    )
    if existing_sent_message:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Outreach message already exists for this draft.",
        )

    # 4. Gate 2 Approval Verification
    if draft.status != OutreachDraftStatus.APPROVED:
        now = datetime.now(timezone.utc)
        err_msg = f"Draft status must be APPROVED before dispatch (current status: {draft.status.value})."
        attempt = SendAttempt(
            draft_id=draft.id,
            lead_id=draft.lead_id,
            recipient_email=draft.recipient_email,
            attempted_at=now,
            result=SendAttemptResult.BLOCKED,
            failure_reason=err_msg,
        )
        db.add(attempt)
        await log_dispatch_audit(
            db=db,
            action="dispatch_blocked",
            owner_email=owner_email,
            status=AgentRunStatus.FAILED,
            error_message=err_msg,
            input_data={"draft_id": str(draft.id), "current_status": draft.status.value},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )

    # 5. SafetyController Comprehensive Authorization
    safety_controller = SafetyController()
    safety_result = await safety_controller.authorize(db, draft_id=draft.id, record_blocked_attempt=True)

    if not safety_result.allowed:
        await log_dispatch_audit(
            db=db,
            action="dispatch_blocked",
            owner_email=owner_email,
            status=AgentRunStatus.FAILED,
            error_message=safety_result.blocked_reason,
            input_data={"draft_id": str(draft.id), "violations": safety_result.violations},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Safety check blocked dispatch: {safety_result.blocked_reason}",
        )

    # 6. Verify Gmail Account Connectivity
    account = await db.scalar(
        select(GmailAccount).where(
            GmailAccount.owner_id == owner_email,
            GmailAccount.connection_status == GmailConnectionStatus.CONNECTED,
        )
    )
    if not account or not account.encrypted_refresh_token:
        now = datetime.now(timezone.utc)
        err_msg = "No active connected Gmail account found for owner."
        attempt = SendAttempt(
            draft_id=draft.id,
            lead_id=draft.lead_id,
            recipient_email=draft.recipient_email,
            attempted_at=now,
            result=SendAttemptResult.BLOCKED,
            failure_reason=err_msg,
        )
        db.add(attempt)
        await log_dispatch_audit(
            db=db,
            action="dispatch_blocked",
            owner_email=owner_email,
            status=AgentRunStatus.FAILED,
            error_message=err_msg,
            input_data={"draft_id": str(draft.id)},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=err_msg,
        )

    # 7. Dispatch via Gmail API
    dispatch_service = GmailDispatchService()
    try:
        dispatch_result = await dispatch_service.dispatch_draft(account=account, draft=draft)
    except GmailDispatchError as exc:
        now = datetime.now(timezone.utc)
        attempt = SendAttempt(
            draft_id=draft.id,
            lead_id=draft.lead_id,
            recipient_email=draft.recipient_email,
            attempted_at=now,
            result=SendAttemptResult.FAILED,
            failure_reason=str(exc),
        )
        db.add(attempt)
        await log_dispatch_audit(
            db=db,
            action="dispatch_failed",
            owner_email=owner_email,
            status=AgentRunStatus.FAILED,
            error_message=str(exc),
            input_data={"draft_id": str(draft.id), "recipient_email": draft.recipient_email},
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gmail API dispatch failed: {str(exc)}",
        )

    # 8. Success: Update Draft, Create OutreachMessage, and Record SendAttempt
    now = dispatch_result.sent_at
    draft.status = OutreachDraftStatus.SENT

    message = OutreachMessage(
        draft_id=draft.id,
        lead_id=draft.lead_id,
        recipient_email=draft.recipient_email,
        subject=draft.subject,
        gmail_message_id=dispatch_result.gmail_message_id,
        gmail_thread_id=dispatch_result.gmail_thread_id,
        sent_at=now,
        status=OutreachMessageStatus.SENT,
    )
    db.add(message)
    await db.flush()

    attempt = SendAttempt(
        draft_id=draft.id,
        lead_id=draft.lead_id,
        recipient_email=draft.recipient_email,
        attempted_at=now,
        result=SendAttemptResult.SUCCESS,
        gmail_message_id=dispatch_result.gmail_message_id,
        gmail_thread_id=dispatch_result.gmail_thread_id,
    )
    db.add(attempt)

    await log_dispatch_audit(
        db=db,
        action="dispatch_success",
        owner_email=owner_email,
        status=AgentRunStatus.COMPLETED,
        input_data={
            "draft_id": str(draft.id),
            "lead_id": str(draft.lead_id),
            "recipient_email": draft.recipient_email,
            "gmail_message_id": dispatch_result.gmail_message_id,
            "gmail_thread_id": dispatch_result.gmail_thread_id,
        },
    )
    await db.commit()

    return GmailDispatchResponse(
        success=True,
        draft_id=draft.id,
        lead_id=draft.lead_id,
        recipient_email=draft.recipient_email,
        subject=draft.subject,
        gmail_message_id=dispatch_result.gmail_message_id,
        gmail_thread_id=dispatch_result.gmail_thread_id,
        sent_at=now,
        status="sent",
    )

