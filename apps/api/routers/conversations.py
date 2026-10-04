"""
Client Conversation Router — Phase 5 Stage 5.1.

Provides authenticated, owner-scoped endpoints for:
- Creating a client conversation from a replied lead
- Fetching/refreshing the Gmail thread for a conversation
- Listing conversations
- Retrieving conversation detail with messages

All endpoints enforce:
- JWT owner authentication via require_owner
- Owner-identity IDOR protection (owner_email from JWT only, never from request body)
- Thread ID sourced from trusted server-side records (never from client request)
- Fail-closed error handling

Stage 5.1 Endpoints:
    POST   /api/v1/conversations                          — create conversation
    GET    /api/v1/conversations                          — list conversations
    GET    /api/v1/conversations/{id}                     — get conversation detail
    POST   /api/v1/conversations/{id}/fetch-thread        — fetch/refresh Gmail thread
"""
from __future__ import annotations

from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from core.config import settings
from core.database import get_db
from models.client_intelligence import (
    ClientClarification,
    ClientConversation,
    ClientConversationMessage,
    ClientConversationStatus,
    ClientRequirement,
    ClientRequirementEvidence,
    ClientRequirementVersion,
)
from routers.auth import require_owner
from schemas import PaginatedResponse
from schemas.client_intelligence import (
    ClarificationResponse,
    ConversationCompletenessResponse,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationMessageResponse,
    ConversationResponse,
    ExtractionResponse,
    RequirementDetailResponse,
    RequirementEvidenceResponse,
    RequirementResponse,
    RequirementVersionResponse,
)
from services.conversation_service import (
    ClientConversationService,
    ConversationDuplicateError,
    ConversationGmailDisconnectedError,
    ConversationGmailError,
    ConversationIneligibleLeadError,
    ConversationLeadNotFoundError,
    ConversationNotFoundError,
    ConversationOwnershipError,
    ConversationThreadNotRelatedError,
)
from services.requirement_extraction_service import RequirementExtractionService

router = APIRouter()
log = structlog.get_logger(__name__)


# ── IDOR Verification ─────────────────────────────────────────────────────────

def verify_owner_access(owner_email: str) -> None:
    """
    IDOR Protection: verify the authenticated JWT owner matches the configured agency owner.
    Prevents foreign or elevated tokens from accessing conversation resources.
    """
    if settings.OWNER_EMAIL and owner_email.lower().strip() != settings.OWNER_EMAIL.lower().strip():
        log.warning(
            "Unauthorized owner access attempt on conversations API",
            caller=owner_email,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not authorized to access this agency's conversation resources.",
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a client conversation",
    description=(
        "Create a new client conversation anchored to a Lead that has a verified prospect reply. "
        "Requires the lead to have at least one Phase 4 InboundMessage. "
        "gmail_thread_id is sourced from the InboundMessage — never from the request body."
    ),
)
async def create_conversation(
    payload: ConversationCreateRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> ConversationResponse:
    """Create a client conversation for a replied lead."""
    verify_owner_access(owner_email)

    service = ClientConversationService()
    try:
        conv = await service.create_conversation(
            lead_id=payload.lead_id,
            owner_email=owner_email,
            db=db,
            inbound_message_id=payload.inbound_message_id,
        )
    except ConversationLeadNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConversationOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ConversationIneligibleLeadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except ConversationDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return ConversationResponse.model_validate(conv)


@router.get(
    "",
    response_model=PaginatedResponse,
    summary="List client conversations",
    description="List all client conversations for the authenticated owner with optional filtering.",
)
async def list_conversations(
    status_filter: Optional[ClientConversationStatus] = Query(
        None, alias="status", description="Filter by conversation status"
    ),
    lead_id: Optional[uuid.UUID] = Query(None, description="Filter by lead ID"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """List conversations for the authenticated owner."""
    verify_owner_access(owner_email)

    service = ClientConversationService()
    offset = (page - 1) * page_size

    conversations, total = await service.list_conversations(
        owner_email=owner_email,
        db=db,
        status_filter=status_filter,
        lead_id_filter=lead_id,
        offset=offset,
        limit=page_size,
    )

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[ConversationResponse.model_validate(c) for c in conversations],
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
    summary="Get conversation detail",
    description="Retrieve a conversation with its normalized messages. Enforces ownership.",
)
async def get_conversation(
    conversation_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailResponse:
    """Retrieve a conversation with all normalized messages."""
    verify_owner_access(owner_email)

    service = ClientConversationService()
    try:
        conv = await service.verify_conversation_ownership(
            conversation_id=conversation_id,
            owner_email=owner_email,
            db=db,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConversationOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    # Audit access
    log.info(
        "Conversation accessed",
        conversation_id=str(conversation_id),
        owner=owner_email,
        status=conv.status.value,
    )

    # Load messages
    messages_rows = (await db.scalars(
        select(ClientConversationMessage)
        .where(ClientConversationMessage.conversation_id == conv.id)
        .order_by(ClientConversationMessage.position.asc())
    )).all()

    return ConversationDetailResponse(
        id=conv.id,
        lead_id=conv.lead_id,
        inbound_message_id=conv.inbound_message_id,
        gmail_thread_id=conv.gmail_thread_id,
        status=conv.status,
        fetched_at=conv.fetched_at,
        message_count=conv.message_count,
        last_message_at=conv.last_message_at,
        intent=conv.intent,
        budget_signal=conv.budget_signal,
        timeline_signal=conv.timeline_signal,
        owner_notes=conv.owner_notes,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[ConversationMessageResponse.model_validate(m) for m in messages_rows],
    )


@router.post(
    "/{conversation_id}/fetch-thread",
    response_model=ConversationDetailResponse,
    summary="Fetch / refresh Gmail thread",
    description=(
        "Fetch the full Gmail thread for this conversation and store normalized messages. "
        "This operation is idempotent — re-fetching the same thread updates existing messages. "
        "Gmail account must be CONNECTED. Thread ID is sourced from the server-side record only."
    ),
)
async def fetch_thread(
    conversation_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> ConversationDetailResponse:
    """Fetch or refresh the Gmail thread for an existing conversation."""
    verify_owner_access(owner_email)

    service = ClientConversationService()
    try:
        conv = await service.fetch_thread(
            conversation_id=conversation_id,
            owner_email=owner_email,
            db=db,
        )
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConversationOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except ConversationGmailDisconnectedError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    except ConversationGmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gmail error: {str(exc)}",
        )

    # Load messages to return in detail response
    messages_rows = (await db.scalars(
        select(ClientConversationMessage)
        .where(ClientConversationMessage.conversation_id == conv.id)
        .order_by(ClientConversationMessage.position.asc())
    )).all()

    return ConversationDetailResponse(
        id=conv.id,
        lead_id=conv.lead_id,
        inbound_message_id=conv.inbound_message_id,
        gmail_thread_id=conv.gmail_thread_id,
        status=conv.status,
        fetched_at=conv.fetched_at,
        message_count=conv.message_count,
        last_message_at=conv.last_message_at,
        intent=conv.intent,
        budget_signal=conv.budget_signal,
        timeline_signal=conv.timeline_signal,
        owner_notes=conv.owner_notes,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[ConversationMessageResponse.model_validate(m) for m in messages_rows],
    )


# ── Phase 5.2 Requirements Endpoints ──────────────────────────────────────────

@router.post(
    "/{conversation_id}/extract-requirements",
    response_model=ExtractionResponse,
    summary="Extract structured requirements from conversation",
    description=(
        "Extracts client requirements from conversation messages deterministically. "
        "Links traceable evidence, tracks version history, and identifies missing critical fields."
    ),
)
async def extract_requirements(
    conversation_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> ExtractionResponse:
    """Extract client requirements, evidence, and clarifications."""
    verify_owner_access(owner_email)

    conv_service = ClientConversationService()
    try:
        conv = await conv_service.verify_conversation_ownership(conversation_id, owner_email, db)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConversationOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    extraction_service = RequirementExtractionService()
    reqs, clarifications, completeness = await extraction_service.extract_and_store_requirements(
        conversation_id=conversation_id,
        owner_email=owner_email,
        db=db,
    )

    req_responses = []
    for r in reqs:
        ev_count = (await db.scalar(
            select(func.count(ClientRequirementEvidence.id))
            .where(ClientRequirementEvidence.requirement_id == r.id)
        )) or 0
        ver_count = (await db.scalar(
            select(func.count(ClientRequirementVersion.id))
            .where(ClientRequirementVersion.requirement_id == r.id)
        )) or 0
        req_responses.append(
            RequirementResponse(
                id=r.id,
                conversation_id=r.conversation_id,
                key=r.key,
                category_group=r.category_group,
                value=r.value,
                status=r.status,
                confidence=r.confidence,
                current_version=r.current_version,
                notes=r.notes,
                evidence_count=ev_count,
                version_count=ver_count,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )

    clarifications_rows = (await db.scalars(
        select(ClientClarification)
        .where(ClientClarification.conversation_id == conversation_id)
        .order_by(ClientClarification.created_at.asc())
    )).all()
    clar_responses = [ClarificationResponse.model_validate(c) for c in clarifications_rows]

    return ExtractionResponse(
        conversation_id=conversation_id,
        status=conv.status,
        requirements_count=len(req_responses),
        clarifications_count=len(clar_responses),
        overall_completeness_percentage=completeness["overall_completeness_percentage"],
        requirements=req_responses,
        clarifications=clar_responses,
    )


@router.get(
    "/{conversation_id}/requirements/completeness",
    response_model=ConversationCompletenessResponse,
    summary="Get requirement completeness assessment",
)
async def get_requirement_completeness(
    conversation_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> ConversationCompletenessResponse:
    """Evaluate deterministic completeness across all 8 standard categories."""
    verify_owner_access(owner_email)

    conv_service = ClientConversationService()
    try:
        await conv_service.verify_conversation_ownership(conversation_id, owner_email, db)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConversationOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    reqs = (await db.scalars(
        select(ClientRequirement).where(ClientRequirement.conversation_id == conversation_id)
    )).all()
    reqs_map = {r.key: r for r in reqs}

    extraction_service = RequirementExtractionService()
    completeness = extraction_service.evaluate_completeness(reqs_map)

    return ConversationCompletenessResponse(
        conversation_id=conversation_id,
        overall_completeness_percentage=completeness["overall_completeness_percentage"],
        overall_status=completeness["overall_status"],
        categories=completeness["categories"],
        total_fields=completeness["total_fields"],
        total_present=completeness["total_present"],
        total_missing=completeness["total_missing"],
    )


@router.get(
    "/{conversation_id}/requirements",
    response_model=List[RequirementResponse],
    summary="List extracted requirements for a conversation",
)
async def list_requirements(
    conversation_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> List[RequirementResponse]:
    """List all client requirements extracted for this conversation."""
    verify_owner_access(owner_email)

    conv_service = ClientConversationService()
    try:
        await conv_service.verify_conversation_ownership(conversation_id, owner_email, db)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConversationOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    reqs = (await db.scalars(
        select(ClientRequirement)
        .where(ClientRequirement.conversation_id == conversation_id)
        .order_by(ClientRequirement.category_group.asc(), ClientRequirement.key.asc())
    )).all()

    responses = []
    for r in reqs:
        ev_count = (await db.scalar(
            select(func.count(ClientRequirementEvidence.id))
            .where(ClientRequirementEvidence.requirement_id == r.id)
        )) or 0
        ver_count = (await db.scalar(
            select(func.count(ClientRequirementVersion.id))
            .where(ClientRequirementVersion.requirement_id == r.id)
        )) or 0
        responses.append(
            RequirementResponse(
                id=r.id,
                conversation_id=r.conversation_id,
                key=r.key,
                category_group=r.category_group,
                value=r.value,
                status=r.status,
                confidence=r.confidence,
                current_version=r.current_version,
                notes=r.notes,
                evidence_count=ev_count,
                version_count=ver_count,
                created_at=r.created_at,
                updated_at=r.updated_at,
            )
        )

    return responses


@router.get(
    "/{conversation_id}/requirements/{requirement_id}",
    response_model=RequirementDetailResponse,
    summary="Get requirement detail with evidence and version history",
)
async def get_requirement_detail(
    conversation_id: uuid.UUID,
    requirement_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> RequirementDetailResponse:
    """Retrieve a single requirement with complete traceable evidence and version history."""
    verify_owner_access(owner_email)

    conv_service = ClientConversationService()
    try:
        await conv_service.verify_conversation_ownership(conversation_id, owner_email, db)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ConversationOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    req = (await db.scalars(
        select(ClientRequirement).where(
            ClientRequirement.id == requirement_id,
            ClientRequirement.conversation_id == conversation_id,
        )
    )).first()

    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Requirement '{requirement_id}' not found for this conversation.",
        )

    evidence_rows = (await db.scalars(
        select(ClientRequirementEvidence)
        .where(ClientRequirementEvidence.requirement_id == req.id)
        .order_by(ClientRequirementEvidence.created_at.asc())
    )).all()

    version_rows = (await db.scalars(
        select(ClientRequirementVersion)
        .where(ClientRequirementVersion.requirement_id == req.id)
        .order_by(ClientRequirementVersion.version_number.asc())
    )).all()

    return RequirementDetailResponse(
        id=req.id,
        conversation_id=req.conversation_id,
        key=req.key,
        category_group=req.category_group,
        value=req.value,
        status=req.status,
        confidence=req.confidence,
        current_version=req.current_version,
        notes=req.notes,
        created_at=req.created_at,
        updated_at=req.updated_at,
        evidence=[RequirementEvidenceResponse.model_validate(e) for e in evidence_rows],
        versions=[RequirementVersionResponse.model_validate(v) for v in version_rows],
    )

