"""
Phase 3 Stage 3.1 Tests — Data Models, Schemas, Constraints & Relationships.

Verifies:
1. OutreachDraft creation & multiple draft history on Lead
2. GmailAccount creation & encrypted_refresh_token security isolation
3. OutreachMessage creation & relationship to Lead and Draft
4. SendAttempt creation & auditability
5. SuppressionRecord email-level and domain-level suppression
6. SuppressionRecord validation prevents empty targets
7. DeliveryEvent creation & relationship to OutreachMessage
8. Existing Lead.research relationship remains 100% intact
9. Policy configuration defaults (30 sends/day, 20 new leads/day, 120s pacing)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.config import settings
from models import (
    DeliveryEvent,
    DeliveryEventType,
    GmailAccount,
    GmailConnectionStatus,
    Lead,
    LeadResearch,
    LeadStatus,
    OutreachDraft,
    OutreachDraftStatus,
    OutreachMessage,
    OutreachMessageStatus,
    SendAttempt,
    SendAttemptResult,
    SuppressionReason,
    SuppressionRecord,
)
from schemas import (
    DeliveryEventResponse,
    GmailAccountCreate,
    GmailAccountResponse,
    OutreachDraftCreate,
    OutreachDraftResponse,
    OutreachMessageResponse,
    SendAttemptResponse,
    SuppressionRecordCreate,
    SuppressionRecordResponse,
)
from tests.conftest import TestSessionLocal


@pytest.fixture
async def db_session():
    """Async session fixture connected to SQLite test database."""
    async with TestSessionLocal() as session:
        yield session


# ── Configuration Policy Tests ────────────────────────────────────────────────

def test_phase3_outreach_policy_defaults():
    """Verify approved Stage 3.1 policy defaults are strictly configured."""
    assert settings.MAX_DAILY_SENDS == 30, "Total send limit must default to 30 sends/day"
    assert settings.MAX_NEW_LEADS_PER_DAY == 20, "New lead limit must default to 20 leads/day"
    assert settings.DOMAIN_PACING_SECONDS == 120, "Same-domain pacing must default to 120 seconds"


# ── Database Model & Relationship Tests ───────────────────────────────────────

@pytest.mark.asyncio
async def test_outreach_draft_creation_and_lead_relationship(db_session: AsyncSession):
    """OutreachDraft must link to Lead and support multiple historical drafts."""
    # Create Lead
    lead = Lead(
        company_name="Apex Plumbing",
        domain="apexplumbing.com",
        source_type="manual_entry",
        status=LeadStatus.APPROVED,
    )
    db_session.add(lead)
    await db_session.flush()

    # Create First Draft
    draft_1 = OutreachDraft(
        lead_id=lead.id,
        recipient_email="contact@apexplumbing.com",
        subject="Website responsiveness audit for Apex Plumbing",
        body_text="Hi Apex team, we noticed your website lacks mobile viewport scaling.",
        body_html="<p>Hi Apex team, we noticed your website lacks mobile viewport scaling.</p>",
        status=OutreachDraftStatus.DRAFTED,
    )
    db_session.add(draft_1)
    await db_session.flush()

    # Create Second Historical Draft for the same lead
    draft_2 = OutreachDraft(
        lead_id=lead.id,
        recipient_email="contact@apexplumbing.com",
        subject="Updated website proposal for Apex Plumbing",
        body_text="Follow-up draft with updated metrics.",
        status=OutreachDraftStatus.PENDING_APPROVAL,
    )
    db_session.add(draft_2)
    await db_session.commit()

    # Reload Lead with eager-loaded drafts
    stmt = (
        select(Lead)
        .options(selectinload(Lead.outreach_drafts))
        .where(Lead.id == lead.id)
    )
    res = await db_session.execute(stmt)
    loaded_lead = res.scalar_one()

    assert len(loaded_lead.outreach_drafts) == 2
    draft_subjects = [d.subject for d in loaded_lead.outreach_drafts]
    assert "Website responsiveness audit for Apex Plumbing" in draft_subjects
    assert "Updated website proposal for Apex Plumbing" in draft_subjects

    # Check back-link to lead
    stmt_draft = (
        select(OutreachDraft)
        .options(selectinload(OutreachDraft.lead))
        .where(OutreachDraft.id == draft_1.id)
    )
    res_draft = await db_session.execute(stmt_draft)
    loaded_draft = res_draft.scalar_one()
    assert loaded_draft.lead.company_name == "Apex Plumbing"


@pytest.mark.asyncio
async def test_gmail_account_token_isolation(db_session: AsyncSession):
    """
    GmailAccount model stores encrypted_refresh_token,
    but GmailAccountResponse schema MUST NEVER expose it.
    """
    account = GmailAccount(
        owner_id="owner@agency.com",
        google_email="outreach@agency.com",
        encrypted_refresh_token="enc:v1:aes-gcm:c2VjcmV0LXRva2VuLWhlcmU=",
        connection_status=GmailConnectionStatus.CONNECTED,
    )
    db_session.add(account)
    await db_session.commit()

    stmt = select(GmailAccount).where(GmailAccount.google_email == "outreach@agency.com")
    res = await db_session.execute(stmt)
    loaded = res.scalar_one()

    # DB has the encrypted token
    assert loaded.encrypted_refresh_token == "enc:v1:aes-gcm:c2VjcmV0LXRva2VuLWhlcmU="
    assert loaded.connection_status == GmailConnectionStatus.CONNECTED

    # Pydantic response schema MUST NOT have the token field
    response_dto = GmailAccountResponse.model_validate(loaded)
    dto_dict = response_dto.model_dump()
    assert "encrypted_refresh_token" not in dto_dict
    assert "refresh_token" not in dto_dict
    assert "token" not in dto_dict
    assert dto_dict["google_email"] == "outreach@agency.com"
    assert dto_dict["connection_status"] == "connected"


@pytest.mark.asyncio
async def test_outreach_message_and_delivery_event(db_session: AsyncSession):
    """OutreachMessage tracks sent messages and links to DeliveryEvents."""
    lead = Lead(
        company_name="Solstice Dental",
        domain="solsticedental.com",
        source_type="manual_entry",
        status=LeadStatus.APPROVED,
    )
    db_session.add(lead)
    await db_session.flush()

    draft = OutreachDraft(
        lead_id=lead.id,
        recipient_email="hello@solsticedental.com",
        subject="Digital consultation for Solstice Dental",
        body_text="Proposal body text",
        status=OutreachDraftStatus.APPROVED,
    )
    db_session.add(draft)
    await db_session.flush()

    # Create OutreachMessage
    message = OutreachMessage(
        draft_id=draft.id,
        lead_id=lead.id,
        recipient_email="hello@solsticedental.com",
        subject="Digital consultation for Solstice Dental",
        gmail_message_id="msg_gmail_123456789",
        gmail_thread_id="thd_gmail_987654321",
        status=OutreachMessageStatus.SENT,
    )
    db_session.add(message)
    await db_session.flush()

    # Add DeliveryEvent with JSON metadata
    event = DeliveryEvent(
        outreach_message_id=message.id,
        event_type=DeliveryEventType.SENT,
        metadata_json={"smtp_code": 250, "gateway": "gmail-api-v1"},
    )
    db_session.add(event)
    await db_session.commit()

    # Verify relationships with selectinload
    stmt = (
        select(OutreachMessage)
        .options(
            selectinload(OutreachMessage.delivery_events),
            selectinload(OutreachMessage.draft),
            selectinload(OutreachMessage.lead),
        )
        .where(OutreachMessage.id == message.id)
    )
    res = await db_session.execute(stmt)
    loaded_msg = res.scalar_one()

    assert loaded_msg.gmail_message_id == "msg_gmail_123456789"
    assert loaded_msg.gmail_thread_id == "thd_gmail_987654321"
    assert len(loaded_msg.delivery_events) == 1
    assert loaded_msg.delivery_events[0].metadata_json["gateway"] == "gmail-api-v1"
    assert loaded_msg.draft is not None
    assert loaded_msg.draft.id == draft.id
    assert loaded_msg.lead.domain == "solsticedental.com"


@pytest.mark.asyncio
async def test_send_attempt_auditability(db_session: AsyncSession):
    """SendAttempt records audit log for blocked and failed attempts."""
    lead = Lead(
        company_name="Nimbus Tech",
        domain="nimbustech.io",
        source_type="manual_entry",
    )
    db_session.add(lead)
    await db_session.flush()

    # Blocked attempt due to pacing
    attempt_blocked = SendAttempt(
        lead_id=lead.id,
        recipient_email="info@nimbustech.io",
        result=SendAttemptResult.BLOCKED,
        failure_reason="Domain pacing violation: 45s since last send (min: 120s)",
    )
    # Successful attempt
    attempt_success = SendAttempt(
        lead_id=lead.id,
        recipient_email="info@nimbustech.io",
        result=SendAttemptResult.SUCCESS,
        gmail_message_id="msg_999",
    )
    db_session.add_all([attempt_blocked, attempt_success])
    await db_session.commit()

    stmt = (
        select(Lead)
        .options(selectinload(Lead.send_attempts))
        .where(Lead.id == lead.id)
    )
    res = await db_session.execute(stmt)
    loaded_lead = res.scalar_one()

    assert len(loaded_lead.send_attempts) == 2
    results = [a.result for a in loaded_lead.send_attempts]
    assert SendAttemptResult.BLOCKED in results
    assert SendAttemptResult.SUCCESS in results


@pytest.mark.asyncio
async def test_suppression_record_email_and_domain(db_session: AsyncSession):
    """SuppressionRecord supports both email-level and domain-level blocks."""
    # Email level
    sup_email = SuppressionRecord(
        email="optout@competitor.com",
        reason=SuppressionReason.OPT_OUT,
        notes="Unsubscribed via footer link",
        source="opt_out_link",
    )
    # Domain level
    sup_domain = SuppressionRecord(
        domain="blocked-domain.com",
        reason=SuppressionReason.MANUAL_BLOCK,
        notes="Owner manual block",
        source="manual",
    )
    db_session.add_all([sup_email, sup_domain])
    await db_session.commit()

    stmt = select(SuppressionRecord)
    res = await db_session.execute(stmt)
    records = res.scalars().all()

    assert len(records) >= 2
    emails = [r.email for r in records if r.email]
    domains = [r.domain for r in records if r.domain]
    assert "optout@competitor.com" in emails
    assert "blocked-domain.com" in domains


def test_suppression_record_schema_validation():
    """SuppressionRecordCreate must reject empty targets (neither email nor domain)."""
    # Valid: email only
    s1 = SuppressionRecordCreate(email="test@domain.com", reason=SuppressionReason.OPT_OUT)
    assert s1.email == "test@domain.com"

    # Valid: domain only
    s2 = SuppressionRecordCreate(domain="domain.com", reason=SuppressionReason.HARD_BOUNCE)
    assert s2.domain == "domain.com"

    # Invalid: neither provided
    with pytest.raises(ValueError, match="At least one of 'email' or 'domain' must be provided"):
        SuppressionRecordCreate(reason=SuppressionReason.SPAM_COMPLAINT)

    # Invalid: empty whitespace strings
    with pytest.raises(ValueError, match="At least one of 'email' or 'domain' must be provided"):
        SuppressionRecordCreate(email="   ", domain="", reason=SuppressionReason.MANUAL_BLOCK)


@pytest.mark.asyncio
async def test_phase2_lead_research_relationship_preserved(db_session: AsyncSession):
    """Preserve existing Phase 2 Lead.research relationship without regression."""
    lead = Lead(
        company_name="Vanguard Logistics",
        domain="vanguardlogistics.com",
        source_type="google_places",
        status=LeadStatus.QUALIFIED,
        qualification_score=75,
    )
    db_session.add(lead)
    await db_session.flush()

    research = LeadResearch(
        lead_id=lead.id,
        has_website=True,
        is_responsive=False,
        has_ssl=True,
        status_code=200,
        load_time_ms=4500,
        tech_stack={"framework": "Wordpress 4.9", "analytics": "Universal Analytics"},
        audit_findings={"speed_penalty": True, "mobile_viewport_missing": True},
    )
    db_session.add(research)
    await db_session.commit()

    stmt = (
        select(Lead)
        .options(selectinload(Lead.research))
        .where(Lead.id == lead.id)
    )
    res = await db_session.execute(stmt)
    loaded = res.scalar_one()

    assert loaded.research is not None
    assert loaded.research.is_responsive is False
    assert loaded.research.tech_stack["framework"] == "Wordpress 4.9"

    stmt_rev = (
        select(LeadResearch)
        .options(selectinload(LeadResearch.lead))
        .where(LeadResearch.id == research.id)
    )
    res_rev = await db_session.execute(stmt_rev)
    loaded_research = res_rev.scalar_one()
    assert loaded_research.lead.company_name == "Vanguard Logistics"
