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


def normalize_text(text: Optional[str]) -> str:
    """Normalize text by lowercasing and stripping non-alphanumeric chars."""
    if not text:
        return ""
    cleaned = re.sub(r"[^\w\s]", "", text.lower())
    return " ".join(cleaned.split())


def extract_city_from_address(address: Optional[str]) -> Optional[str]:
    """Heuristic to extract city from a formatted address string."""
    if not address:
        return None
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 2:
        candidate = parts[-2] if len(parts) >= 3 else parts[0]
        clean = re.sub(r"\d+", "", candidate).strip()
        if clean:
            return clean
    return parts[0] if parts else None


class LeadService:
    """Service layer for Lead entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def is_duplicate(
        self,
        domain: str,
        phone: Optional[str] = None,
        company_name: Optional[str] = None,
        address: Optional[str] = None,
        city: Optional[str] = None,
        google_place_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[Lead]]:
        """
        Check if a lead represents a duplicate of an existing lead, supporting
        multi-location businesses and distinct identities.
        Returns (is_dup, existing_lead).
        """
        # 1. Direct google_place_id check (most specific physical location identifier)
        if google_place_id:
            stmt = select(Lead).where(Lead.google_place_id == google_place_id)
            res = await self.db.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                return True, existing

        clean_domain = normalize_domain(domain)
        clean_phone = normalize_phone(phone) if phone else None
        norm_name = normalize_text(company_name) if company_name else ""
        extracted_city = city or extract_city_from_address(address)
        norm_city = normalize_text(extracted_city) if extracted_city else ""
        norm_address = normalize_text(address) if address else ""

        # Fetch candidate leads that match domain, phone, or company name
        conditions = []
        if clean_domain and not clean_domain.endswith(".local"):
            conditions.append(Lead.domain == clean_domain)
        if clean_phone:
            conditions.append(Lead.phone.is_not(None))
        if norm_name and company_name:
            conditions.append(func.lower(Lead.company_name) == company_name.lower().strip())

        if not conditions:
            return False, None

        from sqlalchemy import or_
        stmt = select(Lead).where(or_(*conditions))
        res = await self.db.execute(stmt)
        candidates = res.scalars().all()

        for ext in candidates:
            # Check google_place_id match if available
            if google_place_id and ext.google_place_id and google_place_id == ext.google_place_id:
                return True, ext

            ext_domain = normalize_domain(ext.domain)
            ext_phone = normalize_phone(ext.phone) if ext.phone else None
            ext_name = normalize_text(ext.company_name)
            ext_extracted_city = ext.city or extract_city_from_address(ext.address)
            ext_city = normalize_text(ext_extracted_city) if ext_extracted_city else ""
            ext_address = normalize_text(ext.address) if ext.address else ""

            # Check phone match
            if clean_phone and ext_phone and clean_phone == ext_phone:
                if (norm_name and ext_name and norm_name == ext_name) or (clean_domain and ext_domain and clean_domain == ext_domain):
                    return True, ext
                if not norm_city or not ext_city or norm_city == ext_city:
                    return True, ext

            # Check domain match
            if clean_domain and ext_domain and clean_domain == ext_domain and not clean_domain.endswith(".local"):
                # Requirement 5: Different businesses sharing a domain -> do NOT merge solely because of domain!
                if norm_name and ext_name and norm_name != ext_name:
                    continue

                # Same company (or company not specified) sharing domain:
                has_cand_loc = bool(norm_city or norm_address)
                has_ext_loc = bool(ext_city or ext_address)

                if has_cand_loc and has_ext_loc:
                    # Both specify a location!
                    # Requirement 4: Same domain, same location -> duplicate!
                    # Requirement 2 & 3: Same domain, different location -> allow separate leads!
                    city_matches = norm_city and ext_city and norm_city == ext_city
                    addr_matches = norm_address and ext_address and (norm_address in ext_address or ext_address in norm_address)
                    if city_matches or addr_matches:
                        return True, ext
                    else:
                        # Legitimate different locations sharing domain -> allow separate
                        continue
                else:
                    # At least one lead lacks location info. Same business name & domain = duplicate
                    if not norm_name or not ext_name or norm_name == ext_name:
                        return True, ext

            # Check same business name + same location
            if norm_name and ext_name and norm_name == ext_name:
                has_cand_loc = bool(norm_city or norm_address)
                has_ext_loc = bool(ext_city or ext_address)
                if has_cand_loc and has_ext_loc:
                    if (norm_city and ext_city and norm_city == ext_city) or (norm_address and ext_address and norm_address == ext_address):
                        return True, ext

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
        place_id = discovered.raw_data.get("place_id")
        city = discovered.city or discovered.raw_data.get("city") or extract_city_from_address(discovered.address)

        # Check deduplication
        is_dup, existing = await self.is_duplicate(
            domain=norm_dom,
            phone=contact.phone or discovered.phone,
            company_name=discovered.company_name,
            address=discovered.address,
            city=city,
            google_place_id=place_id,
        )
        if is_dup and existing:
            log.info("Duplicate lead detected — updating existing record", domain=norm_dom, lead_id=str(existing.id))
            # Update phone/email if existing lacked them
            if not existing.email and contact.email:
                existing.email = contact.email
                existing.email_verification_status = contact.email_verification_status
            if not existing.phone and (contact.phone or discovered.phone):
                existing.phone = contact.phone or discovered.phone
            if not existing.google_place_id and place_id:
                existing.google_place_id = place_id
            if not existing.city and city:
                existing.city = city
            await self.db.flush()
            return existing, False

        # Create new Lead
        lead = Lead(
            company_name=discovered.company_name,
            domain=norm_dom,
            website_url=discovered.website_url,
            google_place_id=place_id,
            phone=contact.phone or discovered.phone,
            email=contact.email,
            email_verification_status=contact.email_verification_status,
            address=discovered.address,
            city=city,
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
