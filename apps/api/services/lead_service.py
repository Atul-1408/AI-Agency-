"""
Lead Service — Handles lead persistence, deduplication, qualification updates, and approval workflows.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from models import (
    ApprovalRequest,
    ApprovalStatus,
    EmailVerificationStatus,
    Lead,
    LeadResearch,
    LeadStatus,
)
from services.discovery.base import DiscoveredLead, normalize_domain
from tools.website_auditor import AuditResult
from tools.contact_finder import ContactInfo
from tools.qualification_scorer import QualificationEvaluation

log = structlog.get_logger(__name__)


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """Clean and normalize phone string to digits only."""
    if not phone:
        return None
    digits = re.sub(r'\D', '', phone)
    return digits if len(digits) >= 7 else phone.strip()


class LeadService:
    """Service layer for Lead entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def is_duplicate(self, domain: str, phone: Optional[str] = None) -> Tuple[bool, Optional[Lead]]:
        """
        Check if a lead with the same domain or phone already exists.
        Returns (is_dup, existing_lead).
        """
        clean_domain = normalize_domain(domain)
        if clean_domain and not clean_domain.endswith(".local"):
            stmt = select(Lead).where(Lead.domain == clean_domain)
            res = await self.db.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                return True, existing

        if phone:
            clean_phone = normalize_phone(phone)
            if clean_phone:
                stmt = select(Lead).where(Lead.phone.is_not(None))
                res = await self.db.execute(stmt)
                all_leads = res.scalars().all()
                for l in all_leads:
                    if l.phone and normalize_phone(l.phone) == clean_phone:
                        return True, l

        return False, None

    async def save_researched_lead(
        self,
        discovered: DiscoveredLead,
        audit: AuditResult,
        contact: ContactInfo,
        evaluation: QualificationEvaluation,
    ) -> Tuple[Lead, bool]:
        """
        Persist a discovered and researched lead with its technical audit details.
        Returns (lead_instance, is_new).
        """
        norm_dom = normalize_domain(discovered.domain) or discovered.domain

        # Check deduplication
        is_dup, existing = await self.is_duplicate(norm_dom, contact.phone or discovered.phone)
        if is_dup and existing:
            log.info("Duplicate lead detected — updating existing record", domain=norm_dom, lead_id=str(existing.id))
            # Update phone/email if existing lacked them
            if not existing.email and contact.email:
                existing.email = contact.email
                existing.email_verification_status = contact.email_verification_status
            if not existing.phone and (contact.phone or discovered.phone):
                existing.phone = contact.phone or discovered.phone
            await self.db.flush()
            return existing, False

        # Create new Lead
        lead = Lead(
            company_name=discovered.company_name,
            domain=norm_dom,
            website_url=discovered.website_url,
            phone=contact.phone or discovered.phone,
            email=contact.email,
            email_verification_status=contact.email_verification_status,
            address=discovered.address,
            industry=discovered.industry,
            qualification_score=evaluation.score,
            status=evaluation.status,
            source_type=discovered.source_type,
            source_query=discovered.source_query,
            source_url=discovered.source_url,
        )
        self.db.add(lead)
        await self.db.flush()

        # Create LeadResearch detail
        research = LeadResearch(
            lead_id=lead.id,
            has_website=audit.has_website,
            is_responsive=audit.is_responsive,
            has_ssl=audit.has_ssl,
            status_code=audit.status_code,
            load_time_ms=audit.load_time_ms,
            copyright_year=audit.copyright_year,
            tech_stack=audit.tech_stack,
            audit_findings={
                "findings": audit.audit_findings,
                "scoring_breakdown": evaluation.scoring_breakdown,
            },
            research_notes=evaluation.qualification_notes,
        )
        self.db.add(research)
        await self.db.flush()

        log.info(
            "Saved researched lead",
            lead_id=str(lead.id),
            domain=lead.domain,
            score=lead.qualification_score,
            status=lead.status.value,
        )
        return lead, True

    async def approve_lead(self, lead_id: uuid.UUID, owner_email: str) -> Lead:
        """Owner approves lead for future outreach (Phase 3)."""
        lead = await self.db.get(Lead, lead_id)
        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        lead.status = LeadStatus.APPROVED
        lead.rejection_reason = None
        await self.db.flush()

        log.info("Lead approved by owner", lead_id=str(lead_id), owner=owner_email)
        return lead

    async def reject_lead(self, lead_id: uuid.UUID, owner_email: str, reason: Optional[str] = None) -> Lead:
        """Owner rejects lead."""
        lead = await self.db.get(Lead, lead_id)
        if not lead:
            raise ValueError(f"Lead {lead_id} not found")

        lead.status = LeadStatus.REJECTED
        lead.rejection_reason = reason or "Rejected by owner"
        await self.db.flush()

        log.info("Lead rejected by owner", lead_id=str(lead_id), owner=owner_email, reason=reason)
        return lead
