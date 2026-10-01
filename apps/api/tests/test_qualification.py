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


def test_scorer_score_boundaries():
    """Verify deterministic boundary thresholds: >=60 QUALIFIED, 30-59 LOW_PRIORITY, <30 DISQUALIFIED."""
    scorer = QualificationScorerTool()

    # Exact boundary checks
    assert scorer.status_for_score(60) == LeadStatus.QUALIFIED
    assert scorer.status_for_score(59) == LeadStatus.LOW_PRIORITY
    assert scorer.status_for_score(30) == LeadStatus.LOW_PRIORITY
    assert scorer.status_for_score(29) == LeadStatus.DISQUALIFIED


def test_scorer_realistic_score_thresholds():
    """Verify realistic factor evaluations produce exact expected LeadStatus tiers."""
    scorer = QualificationScorerTool()

    # Score = 60 (Not responsive 25 + Insecure 15 + Outdated copyright 10 + Email 10 = 60) -> QUALIFIED
    audit_60 = AuditResult(has_website=True, status_code=200, is_responsive=False, has_ssl=False, copyright_year=2018)
    contact_60 = ContactInfo(email="test@biz.com", phone="555-0000")
    res_60 = scorer.evaluate(audit_60, contact_60)
    assert res_60.score == 60
    assert res_60.status == LeadStatus.QUALIFIED

    # Score = 55 (Broken website 35 + Email 10 + Reviews 10 = 55) -> LOW_PRIORITY
    audit_55 = AuditResult(has_website=True, status_code=404)
    contact_55 = ContactInfo(email="test@biz.com", phone="555-0000")
    raw_55 = {"user_ratings_total": 25}
    res_55 = scorer.evaluate(audit_55, contact_55, raw_data=raw_55)
    assert res_55.score == 55
    assert res_55.status == LeadStatus.LOW_PRIORITY

    # Score = 30 (Outdated copyright 10 + Slow TTFB 10 + Email 10 = 30) -> LOW_PRIORITY
    audit_30 = AuditResult(has_website=True, status_code=200, has_ssl=True, is_responsive=True, copyright_year=2018, load_time_ms=3000)
    contact_30 = ContactInfo(email="test@biz.com", phone="555-0000")
    res_30 = scorer.evaluate(audit_30, contact_30)
    assert res_30.score == 30
    assert res_30.status == LeadStatus.LOW_PRIORITY

    # Score = 20 (Outdated copyright 10 + Email 10 = 20) -> DISQUALIFIED
    audit_20 = AuditResult(has_website=True, status_code=200, has_ssl=True, is_responsive=True, copyright_year=2018)
    contact_20 = ContactInfo(email="test@biz.com", phone="555-0000")
    res_20 = scorer.evaluate(audit_20, contact_20)
    assert res_20.score == 20
    assert res_20.status == LeadStatus.DISQUALIFIED
