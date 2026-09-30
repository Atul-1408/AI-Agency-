"""
Tests for QualificationScorerTool and PublicContactFinderTool.
"""
from __future__ import annotations

import pytest

from models import EmailVerificationStatus, LeadStatus
from tools.contact_finder import ContactInfo, PublicContactFinderTool
from tools.qualification_scorer import QualificationScorerTool
from tools.website_auditor import AuditResult


def test_public_contact_finder_extracts_mailto_and_phone():
    """Extracts public business contacts and rejects invalid/asset extensions."""
    finder = PublicContactFinderTool()
    html = """
    <html>
    <body>
        <p>Call our office: <a href="tel:+15125559876">(512) 555-9876</a></p>
        <p>Email: <a href="mailto:info@businesspro.com">Contact Us</a></p>
        <p>Assets: banner@2x.png icon@logo.svg</p>
        <p>Placeholder: test@example.com</p>
    </body>
    </html>
    """
    contact = finder.extract_from_html(html, target_domain="businesspro.com")
    assert contact.email == "info@businesspro.com"
    assert contact.email_verification_status in (EmailVerificationStatus.SYNTAX_VALID, EmailVerificationStatus.MX_VERIFIED)
    assert "512" in (contact.phone or "")


def test_scorer_high_opportunity_prospect():
    """Non-responsive, insecure, outdated site with public email is QUALIFIED (>=60)."""
    scorer = QualificationScorerTool()
    audit = AuditResult(
        has_website=True,
        status_code=200,
        load_time_ms=2900,         # +10 (slow)
        has_ssl=False,              # +15 (no SSL)
        is_responsive=False,        # +25 (not responsive)
        copyright_year=2018,        # +10 (outdated)
        tech_stack={"cms": "WordPress"},
    )
    contact = ContactInfo(
        email="owner@localshop.com",
        email_verification_status=EmailVerificationStatus.SYNTAX_VALID,
        phone="512-555-0000",       # +10 (email available)
    )
    # Total points: 25 + 15 + 10 + 10 + 10 = 70 points
    eval_res = scorer.evaluate(audit, contact)
    assert eval_res.score >= 60
    assert eval_res.status == LeadStatus.QUALIFIED


def test_scorer_modern_framework_penalty():
    """Modern Next.js website receives penalty (-50) and is disqualified."""
    scorer = QualificationScorerTool()
    audit = AuditResult(
        has_website=True,
        status_code=200,
        load_time_ms=200,
        has_ssl=True,
        is_responsive=True,
        copyright_year=2026,
        tech_stack={"framework": "Next.js"},
    )
    contact = ContactInfo(email="hello@agency.io", phone="555-1234")
    eval_res = scorer.evaluate(audit, contact)
    assert eval_res.score < 30
    assert eval_res.status == LeadStatus.DISQUALIFIED


def test_scorer_suppressed_lead():
    """Suppressed leads are unconditionally DISQUALIFIED with score 0."""
    scorer = QualificationScorerTool()
    audit = AuditResult(has_website=False)
    contact = ContactInfo(phone="555-1234")
    eval_res = scorer.evaluate(audit, contact, is_suppressed=True)
    assert eval_res.score == 0
    assert eval_res.status == LeadStatus.DISQUALIFIED
