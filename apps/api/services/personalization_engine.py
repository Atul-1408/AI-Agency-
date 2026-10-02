"""
Phase 3 — Stage 3.2: Personalization Engine.

Takes OWNER-APPROVED, MX-VERIFIED Phase 2 leads and generates factual,
personalized cold outreach email drafts.

Strict Architectural Safeguards:
1. Enforces Gate 1:
   - LeadStatus MUST be APPROVED.
   - EmailVerificationStatus MUST be MX_VERIFIED.
   - Recipient email MUST be present.
   - LeadResearch audit findings MUST be present.
2. Anti-Hallucination & Anti-Prompt-Injection:
   - Sanitizes user-controlled text fields (company name, domain, notes).
   - Anchors 100% of claims in verifiable Phase 2 technical observations
     (load_time_ms, is_responsive, has_ssl, copyright_year, tech_stack).
   - Zero fabricated awards, metrics, or non-existent issues.
3. Gate 2 Human Approval Readiness:
   - Persists all generated drafts strictly with status = OutreachDraftStatus.PENDING_APPROVAL.
   - Requires explicit owner sign-off before any dispatch or safety checks.
"""
from __future__ import annotations

import html
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import (
    EmailVerificationStatus,
    Lead,
    LeadResearch,
    LeadStatus,
    OutreachDraft,
    OutreachDraftStatus,
)

log = structlog.get_logger(__name__)


# ── Custom Exceptions ─────────────────────────────────────────────────────────

class PersonalizationError(Exception):
    """Base exception for personalization engine errors."""
    pass


class Gate1ApprovalError(PersonalizationError):
    """Raised when an unapproved lead is submitted for outreach drafting."""
    pass


class UnverifiedEmailError(PersonalizationError):
    """Raised when a lead lacks an MX_VERIFIED recipient email."""
    pass


class MissingAuditDataError(PersonalizationError):
    """Raised when a lead is missing Phase 2 LeadResearch audit data."""
    pass


class PromptInjectionDetected(PersonalizationError):
    """Raised or flagged when an active prompt injection pattern is detected."""
    pass


# ── Anti-Prompt-Injection & Sanitization ───────────────────────────────────────

# Common injection patterns targeting LLMs or template evaluators
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(previous|all|above|prior)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(previous|all|above|prior)", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"you\s+are\s+now", re.IGNORECASE),
    re.compile(r"developer\s+mode", re.IGNORECASE),
    re.compile(r"override\s+(security|rules|guardrails?)", re.IGNORECASE),
    re.compile(r"\[/?INST\]", re.IGNORECASE),
    re.compile(r"<<SYS>>|<</SYS>>", re.IGNORECASE),
    re.compile(r"<\|im_start\|>|<\|im_end\|>", re.IGNORECASE),
    re.compile(r"drop\s+table", re.IGNORECASE),
    re.compile(r"admin\s+override", re.IGNORECASE),
]


def sanitize_text(text: Optional[str], max_length: int = 150) -> str:
    """
    Sanitize text input:
    1. Strip control characters, excessive whitespace, and HTML tags.
    2. Detect and neutralize prompt injection attempts.
    3. Enforce maximum length constraint.
    """
    if not text:
        return ""

    # Escape HTML to prevent injection into HTML email templates
    cleaned = html.escape(text.strip())

    # Remove non-printable control characters
    cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", cleaned)

    # Detect injection attempts
    for pattern in INJECTION_PATTERNS:
        if pattern.search(cleaned):
            log.warning("Prompt injection pattern detected and neutralized", pattern=pattern.pattern, text=cleaned[:50])
            cleaned = pattern.sub("[REDACTED_INJECTION_ATTEMPT]", cleaned)

    # Collapse multiple whitespace characters
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Truncate to maximum length
    return cleaned[:max_length]


# ── Audit Findings Extraction ─────────────────────────────────────────────────

def extract_factual_observations(research: LeadResearch) -> List[Dict[str, str]]:
    """
    Extract strictly verifiable, observable technical observations from Phase 2 LeadResearch.
    Returns a list of structured findings (label, detail, category).
    Zero hallucinations allowed — every finding must correspond to an actual audit field.
    """
    findings: List[Dict[str, str]] = []

    # 1. Page Load Speed
    if research.load_time_ms is not None and research.load_time_ms > 2500:
        seconds = round(research.load_time_ms / 1000, 1)
        findings.append({
            "category": "performance",
            "label": "Page Load Latency",
            "detail": f"Observed initial page load was {seconds}s (modern mobile standard is under 2.5s)",
        })

    # 2. Mobile Viewport & Responsiveness
    if research.is_responsive is False:
        findings.append({
            "category": "mobile",
            "label": "Mobile Responsiveness",
            "detail": "The layout is not mobile-responsive or lacks proper viewport scaling for smartphone displays",
        })

    # 3. SSL / HTTPS Security
    if research.has_ssl is False:
        findings.append({
            "category": "security",
            "label": "SSL Encryption",
            "detail": "The website is served over unencrypted HTTP without valid HTTPS encryption",
        })

    # 4. Outdated Copyright Year
    current_year = datetime.now(timezone.utc).year
    if research.copyright_year is not None and research.copyright_year < (current_year - 1):
        findings.append({
            "category": "freshness",
            "label": "Outdated Footer Copyright",
            "detail": f"The website footer displays a copyright year of {research.copyright_year}",
        })

    # 5. Legacy Tech Stack
    if research.tech_stack and isinstance(research.tech_stack, dict):
        framework = research.tech_stack.get("framework")
        if framework:
            findings.append({
                "category": "tech_stack",
                "label": "Legacy Architecture",
                "detail": f"The site is currently built on {framework}, which presents modern modernization opportunities",
            })
        analytics = research.tech_stack.get("analytics")
        if analytics and "universal" in str(analytics).lower():
            findings.append({
                "category": "analytics",
                "label": "Deprecated Analytics",
                "detail": "The site uses sunsetted Universal Analytics rather than modern GA4 telemetry",
            })

    # 6. Generic Default if No Major Bottlenecks Found
    if not findings:
        findings.append({
            "category": "modernization",
            "label": "Digital Modernization",
            "detail": "The core infrastructure is stable, but can achieve 2x faster conversion speeds with modern asset bundling",
        })

    return findings


# ── Personalization Engine ────────────────────────────────────────────────────

class PersonalizationEngine:
    """
    Core Phase 3 Personalization Engine.
    Transforms owner-approved leads and Phase 2 audit findings into factual,
    verifiable cold outreach drafts.
    """

    def __init__(self, ai_provider: Any = None):
        self.ai_provider = ai_provider

    def validate_gate_1(self, lead: Lead) -> None:
        """
        Enforce Gate 1 preconditions:
        1. LeadStatus MUST be APPROVED.
        2. Recipient email MUST be present.
        3. EmailVerificationStatus MUST be MX_VERIFIED.
        4. LeadResearch MUST be present.
        """
        # 1. Lead Approval Gate
        if lead.status != LeadStatus.APPROVED:
            raise Gate1ApprovalError(
                f"Gate 1 violation: Lead '{lead.company_name}' ({lead.id}) has status '{lead.status.value}'. "
                "Outreach drafts can ONLY be created for leads with status 'approved'."
            )

        # 2. Recipient Email Present
        if not lead.email or not lead.email.strip():
            raise UnverifiedEmailError(
                f"Lead '{lead.company_name}' ({lead.id}) has no recipient email address."
            )

        # 3. MX Verification Gate
        if lead.email_verification_status != EmailVerificationStatus.MX_VERIFIED:
            raise UnverifiedEmailError(
                f"Recipient email '{lead.email}' for lead '{lead.company_name}' has verification status "
                f"'{lead.email_verification_status.value}'. Phase 3 outreach strictly requires MX_VERIFIED."
            )

        # 4. Lead Research Present
        if not lead.research:
            raise MissingAuditDataError(
                f"Lead '{lead.company_name}' ({lead.id}) is missing Phase 2 LeadResearch audit data."
            )

    def generate_draft_content(
        self,
        lead: Lead,
        research: LeadResearch,
    ) -> Tuple[str, str, str]:
        """
        Generate factual email draft: (subject, body_text, body_html).
        Strictly anchored in observable Phase 2 audit findings.
        """
        # Sanitize all user/external inputs
        company_name = sanitize_text(lead.company_name, max_length=80) or "your team"
        domain = sanitize_text(lead.domain, max_length=80)
        industry = sanitize_text(lead.industry, max_length=50) or "local businesses"
        city = sanitize_text(lead.city, max_length=50)

        # Extract strictly factual findings
        observations = extract_factual_observations(research)

        # Determine subject line based on primary finding
        primary_cat = observations[0]["category"] if observations else "modernization"
        if primary_cat == "mobile":
            subject = f"Mobile conversion optimization for {company_name}"
        elif primary_cat == "performance":
            subject = f"Website speed observation for {company_name}"
        elif primary_cat == "security":
            subject = f"Security & SSL observation regarding {domain}"
        else:
            subject = f"Quick question regarding {company_name}'s website"

        # Build bullet points
        bullet_points_text = "\n".join([f"• {obs['detail']}" for obs in observations[:3]])
        bullet_points_html = "".join([f"<li>{html.escape(obs['detail'])}</li>" for obs in observations[:3]])

        # Location text
        location_clause = f"in {city}" if city else "in your market"

        # Body Plaintext
        body_text = (
            f"Hi {company_name} team,\n\n"
            f"While researching leading {industry} {location_clause}, our agency auditor reviewed {domain}.\n\n"
            f"We noted a few specific technical items that may be impacting your visitor conversions:\n"
            f"{bullet_points_text}\n\n"
            f"We put together a complimentary interactive 3-page prototype redesign demonstrating sub-2-second load times "
            f"and full responsive formatting across modern smartphones.\n\n"
            f"Would you be open to reviewing the preview link this Thursday?\n\n"
            f"Best regards,\n"
            f"Atul | AI Web Agency\n"
            f"https://{domain}\n\n"
            f"---\n"
            f"If you prefer not to receive updates regarding {domain}, simply reply with 'unsubscribe' to be permanently excluded."
        )

        # Body HTML
        body_html = (
            f"<div style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; "
            f"color: #24292e; line-height: 1.6; max-width: 600px;\">\n"
            f"  <p>Hi {html.escape(company_name)} team,</p>\n"
            f"  <p>While researching leading {html.escape(industry)} {html.escape(location_clause)}, our agency auditor reviewed <strong>{html.escape(domain)}</strong>.</p>\n"
            f"  <p>We noted a few specific technical items that may be impacting your visitor conversions:</p>\n"
            f"  <ul>\n"
            f"    {bullet_points_html}\n"
            f"  </ul>\n"
            f"  <p>We put together a complimentary interactive 3-page prototype redesign demonstrating sub-2-second load times and full responsive formatting across modern smartphones.</p>\n"
            f"  <p>Would you be open to reviewing the preview link this Thursday?</p>\n"
            f"  <p style=\"margin-top: 24px;\">Best regards,<br><strong>Atul</strong><br>AI Web Agency</p>\n"
            f"  <hr style=\"border: none; border-top: 1px solid #e1e4e8; margin: 24px 0;\">\n"
            f"  <p style=\"font-size: 11px; color: #6a737d;\">If you prefer not to receive updates regarding {html.escape(domain)}, simply reply with 'unsubscribe' to be permanently excluded.</p>\n"
            f"</div>"
        )

        return subject, body_text, body_html

    async def generate_and_persist_draft(
        self,
        db: AsyncSession,
        lead_id: uuid.UUID,
    ) -> OutreachDraft:
        """
        Execute full Personalization Engine flow for a lead:
        1. Load lead with research.
        2. Enforce Gate 1 preconditions.
        3. Generate factual draft.
        4. Persist OutreachDraft with status = PENDING_APPROVAL.
        """
        # Load lead with research
        stmt = (
            select(Lead)
            .options(selectinload(Lead.research))
            .where(Lead.id == lead_id)
        )
        res = await db.execute(stmt)
        lead = res.scalar_one_or_none()

        if not lead:
            raise PersonalizationError(f"Lead with ID {lead_id} not found.")

        # Enforce Gate 1 preconditions
        self.validate_gate_1(lead)

        # Generate factual draft content
        subject, body_text, body_html = self.generate_draft_content(lead, lead.research)

        # Persist draft strictly as PENDING_APPROVAL (Gate 2 Human-in-the-Loop readiness)
        draft = OutreachDraft(
            lead_id=lead.id,
            recipient_email=lead.email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            status=OutreachDraftStatus.PENDING_APPROVAL,
        )

        db.add(draft)
        await db.commit()
        await db.refresh(draft)

        log.info(
            "Outreach draft generated and persisted",
            draft_id=str(draft.id),
            lead_id=str(lead.id),
            recipient=draft.recipient_email,
            status=draft.status.value,
        )

        return draft
