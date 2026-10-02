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

from datetime import datetime
from typing import Optional
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db
from models.outreach import OutreachDraftStatus
from routers.auth import require_owner
from schemas import PaginatedResponse
from schemas.outreach import (
    OutreachDraftRejectRequest,
    OutreachDraftResponse,
    OutreachDraftUpdateRequest,
)
from services.outreach_service import (
    DraftNotFoundError,
    InvalidStateTransitionError,
    OutreachService,
)

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
