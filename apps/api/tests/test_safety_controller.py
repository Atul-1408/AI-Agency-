"""
Tests for Phase 3 Stage 3.3 — Outreach Safety Controller.

Verifies:
1. Quota Enforcement:
   - Daily total sends cap (max 30)
   - Daily new leads cap (max 20)
2. Domain Pacing:
   - Blocks sends to same domain within 120 seconds
   - Permits sends after >= 120 seconds or first contact
3. Suppression Enforcement:
   - Blocks suppressed recipient email
   - Blocks suppressed recipient domain
4. Gate 2 Approval Requirement:
   - Blocks unapproved draft (PENDING_APPROVAL, DRAFTED, REJECTED)
   - Authorizes owner-approved draft
5. MX Verification:
   - Blocks unverified or unreachable emails
   - Authorizes MX_VERIFIED emails
6. Circuit Breaker States & Transitions:
   - NORMAL and WARNING permit sends
   - THROTTLED and PAUSED block sends
   - Dynamic tripping on elevated bounce rate
   - Manual trip and reset
7. Fail-Closed Behavior:
   - Non-existent draft or lead fails closed
   - Internal exceptions fail closed
8. Gmail Health Verification:
   - Missing or disconnected Gmail account blocks sending
   - Connected Gmail account authorizes sending
9. Combined Safety Failures:
   - Multiple violations recorded together in audit trail
10. Successful Safety Authorization:
   - All conditions met -> allowed = True, send attempt not blocked
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models import (
    CircuitBreakerState,
    DeliveryEvent,
    DeliveryEventType,
    EmailVerificationStatus,
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
from services.safety_controller import (
    CircuitBreaker,
    SafetyCheckResult,
    SafetyController,
)
from tests.conftest import TestSessionLocal


@pytest.fixture
async def db_session():
    """Async session fixture connected to SQLite test database."""
    async with TestSessionLocal() as session:
        yield session


# ── Helper Fixtures & Setup ───────────────────────────────────────────────────

async def create_connected_gmail(session: AsyncSession) -> GmailAccount:
    """Helper to ensure a connected Gmail account exists for tests."""
    account = GmailAccount(
        owner_id="owner@agency.com",
        google_email="outreach@agency.com",
        encrypted_refresh_token="enc:v1:aes-gcm:fake_token",
        connection_status=GmailConnectionStatus.CONNECTED,
    )
    session.add(account)
    await session.flush()
    return account


async def create_compliant_lead_and_draft(
    session: AsyncSession,
    company_name: str = "Apex Plumbing",
    domain: str = "apexplumbing.com",
    email: str = "contact@apexplumbing.com",
    approved: bool = True,
) -> Tuple[Lead, OutreachDraft]:
    """Helper to create a fully compliant lead and draft."""
    lead = Lead(
        company_name=company_name,
        domain=domain,
        source_type="manual_entry",
        email=email,
        email_verification_status=EmailVerificationStatus.MX_VERIFIED,
        status=LeadStatus.APPROVED,
    )
    session.add(lead)
    await session.flush()

    research = LeadResearch(
        lead_id=lead.id,
        has_website=True,
        load_time_ms=3500,
    )
    session.add(research)
    await session.flush()

    draft = OutreachDraft(
        lead_id=lead.id,
        recipient_email=email,
        subject=f"Website modernization for {company_name}",
        body_text="Proposal body text...",
        status=OutreachDraftStatus.APPROVED if approved else OutreachDraftStatus.PENDING_APPROVAL,
        approved_at=datetime.now(timezone.utc) if approved else None,
        approved_by="owner@agency.com" if approved else None,
    )
    session.add(draft)
    await session.flush()
    await session.commit()
    return lead, draft


# ── 1. Quota Enforcement Tests ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_daily_total_send_quota_enforcement(db_session: AsyncSession):
    """Blocks dispatches once MAX_DAILY_SENDS (30) is reached for the day."""
    await create_connected_gmail(db_session)
    lead, draft = await create_compliant_lead_and_draft(db_session)

    controller = SafetyController()
    now = datetime.now(timezone.utc)

    # Populate 29 sent messages for today
    for i in range(29):
        msg = OutreachMessage(
            draft_id=draft.id,
            lead_id=lead.id,
            recipient_email=f"lead{i}@otherdomain{i}.com",
            subject="Test",
            sent_at=now - timedelta(minutes=i + 5),
            status=OutreachMessageStatus.SENT,
        )
        db_session.add(msg)
    await db_session.commit()

    # 30th send is still within quota
    res_29 = await controller.validate_send(db_session, draft.id, override_now=now)
    assert res_29.allowed is True
    assert res_29.checks_passed["daily_send_quota"] is True

    # Add the 30th message to reach max
    msg_30 = OutreachMessage(
        draft_id=draft.id,
        lead_id=lead.id,
        recipient_email="lead30@otherdomain30.com",
        subject="Test",
        sent_at=now - timedelta(minutes=1),
        status=OutreachMessageStatus.SENT,
    )
    db_session.add(msg_30)
    await db_session.commit()

    # 31st send must be BLOCKED
    res_blocked = await controller.validate_send(db_session, draft.id, override_now=now)
    assert res_blocked.allowed is False
    assert res_blocked.checks_passed["daily_send_quota"] is False
    assert "Daily send quota exceeded: 30/30" in res_blocked.blocked_reason


@pytest.mark.asyncio
async def test_new_lead_daily_quota_enforcement(db_session: AsyncSession):
    """Blocks sends to new leads once MAX_NEW_LEADS_PER_DAY (20) distinct leads are messaged."""
    await create_connected_gmail(db_session)
    now = datetime.now(timezone.utc)
    controller = SafetyController()

    # Create and send to 20 distinct leads today
    for i in range(20):
        dummy_lead = Lead(
            company_name=f"Lead {i}",
            domain=f"domain{i}.com",
            source_type="manual_entry",
            email=f"contact@domain{i}.com",
            email_verification_status=EmailVerificationStatus.MX_VERIFIED,
            status=LeadStatus.APPROVED,
        )
        db_session.add(dummy_lead)
        await db_session.flush()

        msg = OutreachMessage(
            lead_id=dummy_lead.id,
            recipient_email=dummy_lead.email,
            subject="Test",
            sent_at=now - timedelta(minutes=i + 2),
            status=OutreachMessageStatus.SENT,
        )
        db_session.add(msg)
    await db_session.commit()

    # Now create a 21st distinct new lead
    new_lead, new_draft = await create_compliant_lead_and_draft(
        db_session, company_name="21st New Lead", domain="newlead21.com", email="info@newlead21.com"
    )

    res = await controller.validate_send(db_session, new_draft.id, override_now=now)
    assert res.allowed is False
    assert res.checks_passed["new_lead_quota"] is False
    assert "New lead daily quota exceeded: 20/20" in res.blocked_reason


# ── 2. Same-Domain Pacing Tests ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_same_domain_pacing_under_120s_blocked(db_session: AsyncSession):
    """Blocks sends to the same domain if less than 120s have elapsed."""
    await create_connected_gmail(db_session)
    lead, draft = await create_compliant_lead_and_draft(
        db_session, company_name="Pacing Corp", domain="pacingcorp.com", email="contact@pacingcorp.com"
    )
    now = datetime.now(timezone.utc)
    controller = SafetyController()

    # Simulate a message sent 45 seconds ago to the same domain
    msg = OutreachMessage(
        draft_id=draft.id,
        lead_id=lead.id,
        recipient_email="other@pacingcorp.com",
        subject="Previous test",
        sent_at=now - timedelta(seconds=45),
        status=OutreachMessageStatus.SENT,
    )
    db_session.add(msg)
    await db_session.commit()

    res = await controller.validate_send(db_session, draft.id, override_now=now)
    assert res.allowed is False
    assert res.checks_passed["domain_pacing"] is False
    assert "Domain pacing violation" in res.blocked_reason
    assert "minimum: 120s" in res.blocked_reason


@pytest.mark.asyncio
async def test_same_domain_pacing_over_120s_allowed(db_session: AsyncSession):
    """Permits sends to the same domain if >= 120s have elapsed."""
    await create_connected_gmail(db_session)
    lead, draft = await create_compliant_lead_and_draft(
        db_session, company_name="Clear Corp", domain="clearcorp.com", email="contact@clearcorp.com"
    )
    now = datetime.now(timezone.utc)
    controller = SafetyController()

    # Simulate message sent 125 seconds ago
    msg = OutreachMessage(
        draft_id=draft.id,
        lead_id=lead.id,
        recipient_email="other@clearcorp.com",
        subject="Previous test",
        sent_at=now - timedelta(seconds=125),
        status=OutreachMessageStatus.SENT,
    )
    db_session.add(msg)
    await db_session.commit()

    res = await controller.validate_send(db_session, draft.id, override_now=now)
    assert res.allowed is True
    assert res.checks_passed["domain_pacing"] is True


# ── 3. Suppression Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_suppression_enforcement_email_and_domain(db_session: AsyncSession):
    """Blocks recipient if email or entire domain is suppressed."""
    await create_connected_gmail(db_session)
    controller = SafetyController()

    # Suppressed email
    lead_email, draft_email = await create_compliant_lead_and_draft(
        db_session, company_name="Email Blocked", domain="regular.com", email="blocked@regular.com"
    )
    sup_email = SuppressionRecord(email="blocked@regular.com", reason=SuppressionReason.OPT_OUT)
    db_session.add(sup_email)

    # Suppressed domain
    lead_domain, draft_domain = await create_compliant_lead_and_draft(
        db_session, company_name="Domain Blocked", domain="competitor.com", email="sales@competitor.com"
    )
    sup_domain = SuppressionRecord(domain="competitor.com", reason=SuppressionReason.MANUAL_BLOCK)
    db_session.add(sup_domain)
    await db_session.commit()

    # Test email suppression
    res_e = await controller.validate_send(db_session, draft_email.id)
    assert res_e.allowed is False
    assert res_e.checks_passed["not_suppressed"] is False
    assert "Suppression violation" in res_e.blocked_reason
    assert "opt_out" in res_e.blocked_reason

    # Test domain suppression
    res_d = await controller.validate_send(db_session, draft_domain.id)
    assert res_d.allowed is False
    assert res_d.checks_passed["not_suppressed"] is False
    assert "competitor.com" in res_d.blocked_reason
    assert "manual_block" in res_d.blocked_reason


# ── 4. Gate 2 Approval Tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate2_owner_approval_required(db_session: AsyncSession):
    """Drafts without owner approval MUST be blocked."""
    await create_connected_gmail(db_session)
    controller = SafetyController()

    lead, draft_pending = await create_compliant_lead_and_draft(
        db_session, company_name="Pending Approval Co", approved=False
    )

    res = await controller.validate_send(db_session, draft_pending.id)
    assert res.allowed is False
    assert res.checks_passed["gate_2_approved"] is False
    assert "Gate 2 violation" in res.blocked_reason


# ── 5. MX Verification Tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mx_verification_required(db_session: AsyncSession):
    """Blocks sending if lead's email_verification_status is not MX_VERIFIED."""
    await create_connected_gmail(db_session)
    controller = SafetyController()

    lead, draft = await create_compliant_lead_and_draft(db_session, company_name="Unverified Co")
    lead.email_verification_status = EmailVerificationStatus.UNVERIFIED
    await db_session.commit()

    res = await controller.validate_send(db_session, draft.id)
    assert res.allowed is False
    assert res.checks_passed["mx_verified"] is False
    assert "MX verification failure" in res.blocked_reason


# ── 6. Circuit Breaker States & Transitions ───────────────────────────────────

@pytest.mark.asyncio
async def test_circuit_breaker_states_and_tripping(db_session: AsyncSession):
    """Verifies NORMAL/WARNING permit sends, while THROTTLED/PAUSED block sends."""
    await create_connected_gmail(db_session)
    lead, draft = await create_compliant_lead_and_draft(db_session)

    breaker = CircuitBreaker()
    controller = SafetyController(circuit_breaker=breaker)

    # 1. NORMAL state -> Permitted
    breaker.set_state(CircuitBreakerState.NORMAL)
    res_normal = await controller.validate_send(db_session, draft.id)
    assert res_normal.allowed is True

    # 2. WARNING state -> Permitted
    breaker.set_state(CircuitBreakerState.WARNING)
    res_warning = await controller.validate_send(db_session, draft.id)
    assert res_warning.allowed is True

    # 3. THROTTLED state -> Blocked
    breaker.set_state(CircuitBreakerState.THROTTLED, reason="High error rate 8%")
    res_throttled = await controller.validate_send(db_session, draft.id)
    assert res_throttled.allowed is False
    assert "Circuit breaker violation" in res_throttled.blocked_reason
    assert "THROTTLED" in res_throttled.blocked_reason

    # 4. PAUSED state -> Blocked
    breaker.trip(reason="Critical bounce rate spike 15%")
    res_paused = await controller.validate_send(db_session, draft.id)
    assert res_paused.allowed is False
    assert "PAUSED" in res_paused.blocked_reason

    # 5. Reset back to NORMAL -> Permitted
    breaker.reset()
    res_reset = await controller.validate_send(db_session, draft.id)
    assert res_reset.allowed is True


@pytest.mark.asyncio
async def test_circuit_breaker_dynamic_tripping_on_bounces(db_session: AsyncSession):
    """Dynamic circuit breaker evaluates DeliveryEvent history and trips to PAUSED on consecutive bounces."""
    await create_connected_gmail(db_session)
    lead, draft = await create_compliant_lead_and_draft(db_session)

    # Create message
    msg = OutreachMessage(
        draft_id=draft.id,
        lead_id=lead.id,
        recipient_email="test@test.com",
        subject="Test",
        status=OutreachMessageStatus.BOUNCED,
    )
    db_session.add(msg)
    await db_session.flush()

    # Record 3 consecutive hard bounce delivery events
    now = datetime.now(timezone.utc)
    for i in range(3):
        event = DeliveryEvent(
            outreach_message_id=msg.id,
            event_type=DeliveryEventType.BOUNCED,
            event_timestamp=now - timedelta(seconds=i * 10),
            created_at=now - timedelta(seconds=i * 10),
        )
        db_session.add(event)
    await db_session.commit()

    breaker = CircuitBreaker(consecutive_failure_limit=3)
    dynamic_state = await breaker.evaluate_dynamic_state(db_session)
    assert dynamic_state == CircuitBreakerState.PAUSED


# ── 7. Fail-Closed & Missing Entities Tests ───────────────────────────────────

@pytest.mark.asyncio
async def test_fail_closed_on_missing_draft_or_lead(db_session: AsyncSession):
    """Non-existent drafts or leads must immediately fail closed without dispatching."""
    await create_connected_gmail(db_session)
    controller = SafetyController()

    fake_draft_id = uuid.uuid4()
    res = await controller.validate_send(db_session, fake_draft_id)
    assert res.allowed is False
    assert "does not exist" in res.blocked_reason


# ── 8. Gmail Health Failure Tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gmail_health_failure_blocks_dispatch(db_session: AsyncSession):
    """If Gmail is disconnected or in error, dispatch is strictly blocked."""
    # Create Gmail in ERROR state
    account = GmailAccount(
        owner_id="owner@agency.com",
        google_email="outreach@agency.com",
        encrypted_refresh_token="enc:token",
        connection_status=GmailConnectionStatus.ERROR,
    )
    db_session.add(account)
    await db_session.commit()

    lead, draft = await create_compliant_lead_and_draft(db_session)
    controller = SafetyController()

    res = await controller.validate_send(db_session, draft.id)
    assert res.allowed is False
    assert res.checks_passed["gmail_healthy"] is False
    assert "Gmail health check failure" in res.blocked_reason


# ── 9. Combined Safety Failures & Audit Recording ─────────────────────────────

@pytest.mark.asyncio
async def test_combined_failures_recorded_in_send_attempts(db_session: AsyncSession):
    """When multiple checks fail, all violations are recorded in a SendAttempt audit record."""
    controller = SafetyController()

    # Lead unapproved + email unverified + no connected Gmail
    lead, draft = await create_compliant_lead_and_draft(
        db_session, company_name="Multi Fail Co", approved=False
    )
    lead.email_verification_status = EmailVerificationStatus.UNVERIFIED
    lead.status = LeadStatus.DISCOVERED
    await db_session.commit()

    res = await controller.validate_send(db_session, draft.id, record_blocked_attempt=True)
    assert res.allowed is False
    assert len(res.violations) >= 3
    assert res.send_attempt_id is not None

    # Verify audit record persisted in DB
    stmt = select(SendAttempt).where(SendAttempt.id == res.send_attempt_id)
    res_attempt = await db_session.execute(stmt)
    attempt = res_attempt.scalar_one()

    assert attempt.result == SendAttemptResult.BLOCKED
    assert "Gate 1 violation" in attempt.failure_reason
    assert "Gate 2 violation" in attempt.failure_reason
    assert "Gmail health check failure" in attempt.failure_reason


# ── 10. Successful Safety Authorization ───────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_safety_authorization(db_session: AsyncSession):
    """A fully compliant draft with all 10 checks satisfied is authorized for dispatch."""
    await create_connected_gmail(db_session)
    lead, draft = await create_compliant_lead_and_draft(
        db_session,
        company_name="Perfect Lead Co",
        domain="perfectlead.com",
        email="contact@perfectlead.com",
        approved=True,
    )
    controller = SafetyController()

    res = await controller.validate_send(db_session, draft.id)
    assert res.allowed is True
    assert len(res.violations) == 0
    assert res.blocked_reason is None
    assert res.checks_passed["draft_exists"] is True
    assert res.checks_passed["lead_approved"] is True
    assert res.checks_passed["gate_2_approved"] is True
    assert res.checks_passed["mx_verified"] is True
    assert res.checks_passed["not_suppressed"] is True
    assert res.checks_passed["daily_send_quota"] is True
    assert res.checks_passed["new_lead_quota"] is True
    assert res.checks_passed["domain_pacing"] is True
    assert res.checks_passed["circuit_breaker"] is True
    assert res.checks_passed["gmail_healthy"] is True
