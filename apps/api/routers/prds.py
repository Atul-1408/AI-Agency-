"""
PRD Router — Phase 5 Stage 5.3.

Provides authenticated, owner-scoped endpoints for:
- Listing PRD records
- Retrieving PRD detail with requirement references and completeness
- Gate 4 owner approval
- Gate 4 owner rejection

All endpoints enforce:
- JWT owner authentication via require_owner
- IDOR protection: owner_email from JWT only, never from request body
- Gate 4 safeguards: only human owner can approve/reject; approved PRDs are strictly immutable
- Fail-closed error handling
"""
from __future__ import annotations

from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from core.config import settings
from core.database import get_db
from models.client_intelligence import PRDStatus
from routers.auth import require_owner
from schemas.client_intelligence import (
    ConversationCompletenessResponse,
    PRDApproveRequest,
    PRDDetailResponse,
    PRDGenerateRequest,
    PRDRejectRequest,
    PRDRequirementReferenceResponse,
    PRDResponse,
)
from services.prd_generation_service import (
    PRDConversationNotFoundError,
    PRDError,
    PRDGenerationService,
    PRDImmutableError,
    PRDInvalidStatusError,
    PRDNoRequirementsError,
    PRDNotFoundError,
    PRDOwnershipError,
    PRDValidationError,
)

router = APIRouter()
log = structlog.get_logger(__name__)


def verify_owner_access(owner_email: str) -> None:
    """
    IDOR Protection: verify the authenticated JWT owner matches the configured agency owner.
    """
    if settings.OWNER_EMAIL and owner_email.lower().strip() != settings.OWNER_EMAIL.lower().strip():
        log.warning(
            "Unauthorized owner access attempt on PRD API",
            caller=owner_email,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You are not authorized to access this agency's PRD resources.",
        )


@router.post(
    "",
    response_model=PRDDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate PRD from verified conversation requirements (Gate 4 draft)",
)
@router.post(
    "/generate",
    response_model=PRDDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate PRD from verified conversation requirements (Gate 4 draft)",
)
async def generate_prd(
    payload: PRDGenerateRequest,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PRDDetailResponse:
    """
    Generate a Product Requirement Document (PRD) deterministically from verified requirements.

    Security & Gate 4:
    - Enforces owner access.
    - Newly generated PRD starts in PENDING_APPROVAL.
    - Only valid/confirmed requirements are used as authoritative input.
    - Traceability to requirement IDs, versions, and email evidence is preserved.
    """
    verify_owner_access(owner_email)

    service = PRDGenerationService()
    try:
        prd = await service.generate_prd(payload.conversation_id, owner_email, db)
        prd_obj, refs, completeness = await service.get_prd(prd.id, owner_email, db)
    except PRDConversationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PRDOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except PRDNoRequirementsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except (PRDInvalidStatusError, PRDValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return PRDDetailResponse(
        id=prd_obj.id,
        owner_email=prd_obj.owner_email,
        lead_id=prd_obj.lead_id,
        conversation_id=prd_obj.conversation_id,
        version=prd_obj.version,
        status=prd_obj.status,
        title=prd_obj.title,
        executive_summary=prd_obj.executive_summary,
        business_overview=prd_obj.business_overview,
        goals=prd_obj.goals,
        target_audience=prd_obj.target_audience,
        sitemap=prd_obj.sitemap,
        content_requirements=prd_obj.content_requirements,
        functionality_requirements=prd_obj.functionality_requirements,
        design_requirements=prd_obj.design_requirements,
        branding_requirements=prd_obj.branding_requirements,
        contact_requirements=prd_obj.contact_requirements,
        technical_requirements=prd_obj.technical_requirements,
        timeline=prd_obj.timeline,
        budget=prd_obj.budget,
        assumptions=prd_obj.assumptions,
        open_questions=prd_obj.open_questions,
        requirement_traceability=prd_obj.requirement_traceability,
        generated_at=prd_obj.generated_at,
        approved_at=prd_obj.approved_at,
        approved_by=prd_obj.approved_by,
        rejected_at=prd_obj.rejected_at,
        rejected_by=prd_obj.rejected_by,
        rejection_reason=prd_obj.rejection_reason,
        created_at=prd_obj.created_at,
        updated_at=prd_obj.updated_at,
        requirement_references=[
            PRDRequirementReferenceResponse.model_validate(r) for r in refs
        ],
        completeness=ConversationCompletenessResponse(
            conversation_id=prd_obj.conversation_id,
            overall_completeness_percentage=completeness["overall_completeness_percentage"],
            overall_status=completeness["overall_status"],
            categories=completeness["categories"],
            total_fields=completeness["total_fields"],
            total_present=completeness["total_present"],
            total_missing=completeness["total_missing"],
        ),
    )


@router.get(
    "",
    response_model=List[PRDResponse],
    summary="List PRDs for authenticated owner",
)
async def list_prds(
    conversation_id: Optional[uuid.UUID] = Query(default=None, description="Optional conversation filter"),
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> List[PRDResponse]:
    """Retrieve all PRD records belonging to the authenticated owner."""
    verify_owner_access(owner_email)

    service = PRDGenerationService()
    prds = await service.list_prds(owner_email, conversation_id, db)
    return [PRDResponse.model_validate(p) for p in prds]


@router.get(
    "/{prd_id}",
    response_model=PRDDetailResponse,
    summary="Get PRD details with requirement references and completeness",
)
async def get_prd_detail(
    prd_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PRDDetailResponse:
    """Retrieve full PRD record with traceable requirement references and completeness metrics."""
    verify_owner_access(owner_email)

    service = PRDGenerationService()
    try:
        prd, refs, completeness = await service.get_prd(prd_id, owner_email, db)
    except PRDNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PRDOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))

    return PRDDetailResponse(
        id=prd.id,
        owner_email=prd.owner_email,
        lead_id=prd.lead_id,
        conversation_id=prd.conversation_id,
        version=prd.version,
        status=prd.status,
        title=prd.title,
        executive_summary=prd.executive_summary,
        business_overview=prd.business_overview,
        goals=prd.goals,
        target_audience=prd.target_audience,
        sitemap=prd.sitemap,
        content_requirements=prd.content_requirements,
        functionality_requirements=prd.functionality_requirements,
        design_requirements=prd.design_requirements,
        branding_requirements=prd.branding_requirements,
        contact_requirements=prd.contact_requirements,
        technical_requirements=prd.technical_requirements,
        timeline=prd.timeline,
        budget=prd.budget,
        assumptions=prd.assumptions,
        open_questions=prd.open_questions,
        requirement_traceability=prd.requirement_traceability,
        generated_at=prd.generated_at,
        approved_at=prd.approved_at,
        approved_by=prd.approved_by,
        rejected_at=prd.rejected_at,
        rejected_by=prd.rejected_by,
        rejection_reason=prd.rejection_reason,
        created_at=prd.created_at,
        updated_at=prd.updated_at,
        requirement_references=[
            PRDRequirementReferenceResponse.model_validate(r) for r in refs
        ],
        completeness=ConversationCompletenessResponse(
            conversation_id=prd.conversation_id,
            overall_completeness_percentage=completeness["overall_completeness_percentage"],
            overall_status=completeness["overall_status"],
            categories=completeness["categories"],
            total_fields=completeness["total_fields"],
            total_present=completeness["total_present"],
            total_missing=completeness["total_missing"],
        ),
    )


@router.post(
    "/{prd_id}/approve",
    response_model=PRDResponse,
    summary="Gate 4: Authenticated owner approves the PRD",
)
async def approve_prd(
    prd_id: uuid.UUID,
    payload: Optional[PRDApproveRequest] = None,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PRDResponse:
    """
    Gate 4 Owner Review: Owner approves the PRD.

    - Transitions status to APPROVED.
    - Locks the PRD as immutable.
    - Records audit log prd_approved.
    - Updates conversation status to PRD_APPROVED.
    """
    verify_owner_access(owner_email)

    notes = payload.notes if payload else None
    service = PRDGenerationService()
    try:
        prd = await service.approve_prd(prd_id, owner_email, notes, db)
    except PRDNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PRDOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except PRDImmutableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PRDInvalidStatusError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return PRDResponse.model_validate(prd)


@router.post(
    "/{prd_id}/reject",
    response_model=PRDResponse,
    summary="Gate 4: Authenticated owner rejects the PRD",
)
async def reject_prd(
    prd_id: uuid.UUID,
    payload: Optional[PRDRejectRequest] = None,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PRDResponse:
    """
    Gate 4 Owner Review: Owner rejects the PRD.

    - Transitions status to REJECTED.
    - Records rejection reason and audit event prd_rejected.
    - A rejected PRD cannot be treated as approved.
    """
    verify_owner_access(owner_email)

    rejection_reason = payload.rejection_reason if payload else None
    service = PRDGenerationService()
    try:
        prd = await service.reject_prd(prd_id, owner_email, rejection_reason, db)
    except PRDNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except PRDOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    except PRDImmutableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except PRDInvalidStatusError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return PRDResponse.model_validate(prd)
