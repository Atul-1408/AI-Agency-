"""
Lead Router — Phase 2.
Covers:
  - Triggering lead research runs (Google Places or Manual)
  - Direct manual prospect creation
  - Listing and filtering leads
  - Viewing full technical audit findings
  - Human approval gate (Approve / Reject leads)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.database import get_db
from models import AgentRun, AgentRunStatus, EmailVerificationStatus, Lead, LeadResearch, LeadStatus
from routers.auth import require_owner
from schemas import (
    AgentRunResponse,
    DiscoverLeadsRequest,
    LeadRejectRequest,
    LeadResponse,
    ManualLeadCreateRequest,
    PaginatedResponse,
)
from services.discovery import normalize_domain
from services.lead_service import LeadService
from tools import PublicContactFinderTool, QualificationScorerTool, WebsiteAuditorTool

router = APIRouter()
log = structlog.get_logger(__name__)


@router.post("/discover", response_model=AgentRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def discover_leads(
    request: DiscoverLeadsRequest,
    _owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> AgentRunResponse:
    """
    Trigger lead discovery and research run.
    Max 20 leads per batch.
    Creates an AgentRun record and enqueues to ARQ worker.
    """
    # 1. Create audit record
    run = AgentRun(
        agent_name="lead_research",
        status=AgentRunStatus.PENDING,
        input_data=request.model_dump(),
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()

    # 2. Enqueue via ARQ (with fallback if Redis is offline)
    try:
        from arq import create_pool
        from core.redis import get_arq_redis_settings
        pool = await create_pool(get_arq_redis_settings())
        job = await pool.enqueue_job(
            "run_lead_research_agent",
            str(run.id),
            request.model_dump(),
        )
        if job:
            run.job_id = job.job_id
        await pool.aclose()
        log.info("Lead research job enqueued", run_id=str(run.id), query=request.query)
    except Exception as exc:
        log.warning("Could not enqueue ARQ job — running synchronously in background or recording error", error=str(exc))
        # If Redis is not available, execute directly to support local/test environments
        try:
            from agents.lead_research import LeadResearchAgent
            agent = LeadResearchAgent()
            output = await agent.execute(db=db, run=run, input_data=request.model_dump())
            run.status = AgentRunStatus.COMPLETED
            run.output_data = output
            run.completed_at = datetime.now(timezone.utc)
        except Exception as inner_exc:
            run.status = AgentRunStatus.FAILED
            run.error_message = f"Failed to execute lead research: {str(inner_exc)[:200]}"
            run.completed_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(run)
    return AgentRunResponse.model_validate(run)


@router.post("/manual", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
async def create_manual_lead(
    request: ManualLeadCreateRequest,
    _owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    """
    Manually add a business prospect and immediately perform technical audit and qualification.
    """
    raw_domain = request.domain or (normalize_domain(request.website_url) if request.website_url else "")
    domain = normalize_domain(raw_domain) or f"manual-{request.company_name.lower().replace(' ', '-')[:25]}.local"

    from services.lead_service import extract_city_from_address
    city = request.city or extract_city_from_address(request.address)

    lead_service = LeadService(db)
    is_dup, existing = await lead_service.is_duplicate(
        domain=domain,
        phone=request.phone,
        company_name=request.company_name,
        address=request.address,
        city=city,
    )
    if is_dup and existing:
        raise HTTPException(
            status_code=400,
            detail=f"Lead with domain '{domain}', phone, or location already exists (Lead ID: {existing.id})",
        )

    # Technical audit
    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.1, timeout_seconds=8.0)
    audit = await auditor.audit(request.website_url)

    # Contact extraction
    contact_finder = PublicContactFinderTool()
    contact = contact_finder.extract_from_html(audit.html_content or "", target_domain=domain)
    if not contact.phone and request.phone:
        contact.phone = request.phone

    # Qualification scoring
    scorer = QualificationScorerTool()
    evaluation = scorer.evaluate(audit, contact)

    # Persist
    from services.discovery import DiscoveredLead
    disc = DiscoveredLead(
        company_name=request.company_name,
        domain=domain,
        website_url=request.website_url,
        phone=request.phone,
        address=request.address,
        city=city,
        industry=request.industry,
        source_type="manual_entry",
        source_query="manual",
        source_url=request.website_url,
        raw_data={"notes": request.notes, "city": city},
    )

    saved_lead, _ = await lead_service.save_researched_lead(disc, audit, contact, evaluation)
    await db.commit()

    # Re-fetch with research relationship
    stmt = select(Lead).options(selectinload(Lead.research)).where(Lead.id == saved_lead.id)
    res = await db.execute(stmt)
    full_lead = res.scalar_one()

    return LeadResponse.model_validate(full_lead)


@router.get("", response_model=PaginatedResponse)
async def list_leads(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    lead_status: Optional[LeadStatus] = Query(None, alias="status"),
    min_score: Optional[int] = Query(None, ge=0, le=100),
    industry: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    _owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse:
    """List leads with optional status, score, and search filtering."""
    q = select(Lead).options(selectinload(Lead.research))

    if lead_status:
        q = q.where(Lead.status == lead_status)
    if min_score is not None:
        q = q.where(Lead.qualification_score >= min_score)
    if industry:
        q = q.where(Lead.industry == industry)
    if search:
        search_filter = f"%{search.lower()}%"
        q = q.where(
            func.lower(Lead.company_name).like(search_filter)
            | func.lower(Lead.domain).like(search_filter)
        )

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(
            q.order_by(Lead.qualification_score.desc(), Lead.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[LeadResponse.model_validate(r) for r in rows],
    )


@router.get("/{lead_id}", response_model=LeadResponse)
async def get_lead(
    lead_id: uuid.UUID,
    _owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    """Get single lead with full technical audit findings."""
    stmt = select(Lead).options(selectinload(Lead.research)).where(Lead.id == lead_id)
    res = await db.execute(stmt)
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return LeadResponse.model_validate(lead)


@router.post("/{lead_id}/qualify", response_model=LeadResponse)
async def requalify_lead(
    lead_id: uuid.UUID,
    _owner: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    """Re-audit and re-qualify a lead."""
    stmt = select(Lead).options(selectinload(Lead.research)).where(Lead.id == lead_id)
    res = await db.execute(stmt)
    lead = res.scalar_one_or_none()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    auditor = WebsiteAuditorTool(crawl_delay_seconds=0.1, timeout_seconds=8.0)
    audit = await auditor.audit(lead.website_url)

    contact_finder = PublicContactFinderTool()
    contact = contact_finder.extract_from_html(audit.html_content or "", target_domain=lead.domain)
    if not contact.phone and lead.phone:
        contact.phone = lead.phone

    scorer = QualificationScorerTool()
    evaluation = scorer.evaluate(audit, contact)

    lead.qualification_score = evaluation.score
    lead.status = evaluation.status
    if contact.email and not lead.email:
        lead.email = contact.email
        lead.email_verification_status = contact.email_verification_status

    if lead.research:
        lead.research.has_website = audit.has_website
        lead.research.is_responsive = audit.is_responsive
        lead.research.has_ssl = audit.has_ssl
        lead.research.status_code = audit.status_code
        lead.research.load_time_ms = audit.load_time_ms
        lead.research.copyright_year = audit.copyright_year
        lead.research.tech_stack = audit.tech_stack
        lead.research.audit_findings = {
            "findings": audit.audit_findings,
            "scoring_breakdown": evaluation.scoring_breakdown,
        }
        lead.research.research_notes = evaluation.qualification_notes

    await db.commit()
    stmt = select(Lead).options(selectinload(Lead.research)).where(Lead.id == lead_id)
    res = await db.execute(stmt)
    return LeadResponse.model_validate(res.scalar_one())


@router.post("/{lead_id}/approve", response_model=LeadResponse)
async def approve_lead(
    lead_id: uuid.UUID,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    """Human approval gate: Owner approves lead for Phase 3 outreach."""
    lead_service = LeadService(db)
    try:
        lead = await lead_service.approve_lead(lead_id, owner_email)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    stmt = select(Lead).options(selectinload(Lead.research)).where(Lead.id == lead_id)
    res = await db.execute(stmt)
    return LeadResponse.model_validate(res.scalar_one())


@router.post("/{lead_id}/reject", response_model=LeadResponse)
async def reject_lead(
    lead_id: uuid.UUID,
    payload: Optional[LeadRejectRequest] = None,
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> LeadResponse:
    """Human approval gate: Owner rejects lead."""
    lead_service = LeadService(db)
    reason = payload.reason if payload else None
    try:
        lead = await lead_service.reject_lead(lead_id, owner_email, reason=reason)
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    stmt = select(Lead).options(selectinload(Lead.research)).where(Lead.id == lead_id)
    res = await db.execute(stmt)
    return LeadResponse.model_validate(res.scalar_one())
