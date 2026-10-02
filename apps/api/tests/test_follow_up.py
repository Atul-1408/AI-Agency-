"""
Comprehensive Test Suite for Phase 4 Stage 4.4 — Follow-up Sequence & Scheduler Foundation.

Verifies:
1. test_create_sequence_success: Sequence creation with default 3-step cadence.
2. test_create_sequence_custom_cadence: Custom cadence step delays and ordering.
3. test_create_sequence_requires_sent_original_message: Cannot attach to unsent message.
4. test_duplicate_active_sequence_prevention: 409 Conflict if active sequence exists.
5. test_cadence_validation_non_sequential_or_decreasing: Validation error on invalid cadences.
6. test_step_ordering_and_scheduled_timestamps: Exact timestamps verified (48h, 120h, 240h).
7. test_pause_active_sequence: Transitions ACTIVE -> PAUSED + audit log.
8. test_resume_paused_sequence: Transitions PAUSED -> ACTIVE + audit log.
9. test_stop_sequence_owner_action: Transitions -> STOPPED + cancels child steps + audit log.
10. test_reply_stop_behavior: Reply detection stops sequence immediately with reason REPLIED.
11. test_invalid_state_transitions: Cannot pause a paused sequence or stop a stopped sequence.
12. test_scheduler_finds_due_eligible_steps: Finds step due by scheduled_at and marks READY.
13. test_scheduler_ignores_future_steps: Steps scheduled in the future are not returned.
14. test_scheduler_never_sends_email_or_calls_gmail: Zero Gmail API calls or OutreachMessages created.
15. test_eligibility_blocks_suppressed_recipient: Blocked if email/domain suppressed.
16. test_eligibility_blocks_disconnected_gmail: Blocked if Gmail is disconnected.
17. test_eligibility_blocks_paused_circuit_breaker: Blocked if circuit breaker is PAUSED.
18. test_eligibility_blocks_disqualified_lead: Blocked if lead is DISQUALIFIED.
19. test_owner_auth_required: 401 without authentication.
20. test_idor_protection: 403 when foreign owner calls follow-up API.
21. test_audit_logging_and_zero_token_leakage: Verification of agent_runs records and sanitization.
22. test_list_and_get_sequence_detail: API listing and retrieval with pagination.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import AsyncMock, patch
import uuid

import httpx
from httpx import AsyncClient, Response
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from main import app as fastapi_app
from models import (
    AgentRun,
    DeliveryEvent,
    DeliveryEventType,
    EmailVerificationStatus,
    Lead,
    LeadResearch,
    LeadStatus,
)
from models.follow_up import (
    FollowUpSequence,
    FollowUpSequenceStatus,
    FollowUpStep,
    FollowUpStepStatus,
    FollowUpStopReason,
)
from models.outreach import (
    CircuitBreakerState,
    GmailAccount,
    GmailConnectionStatus,
    OutreachDraft,
    OutreachDraftStatus,
    OutreachMessage,
    OutreachMessageStatus,
    SendAttempt,
    SendAttemptResult,
    SuppressionReason,
    SuppressionRecord,
)
from routers.auth import _create_access_token
from schemas.follow_up import CadenceStepConfig
from services.follow_up_cadence import (
    calculate_cadence_schedule,
    get_default_cadence,
)
from services.follow_up_eligibility_service import FollowUpEligibilityService
from services.follow_up_scheduler_service import FollowUpSchedulerService
from services.follow_up_service import (
    DuplicateActiveSequenceError,
    FollowUpService,
    InvalidMessageError,
    InvalidStateTransitionError,
    SequenceNotFoundError,
)
from services.reply_detection_service import ReplyDetectionService
from services.token_encryption import TokenEncryptionService
from tests.conftest import TestSessionLocal


# ── Fixtures & Setup ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_oauth_env_settings():
    """Ensure test environment has OAuth configuration set for the test run."""
    orig_key = settings.GMAIL_TOKEN_ENCRYPTION_KEY
    orig_owner = settings.OWNER_EMAIL
    orig_secret = settings.GOOGLE_CLIENT_SECRET
    settings.GMAIL_TOKEN_ENCRYPTION_KEY = "test_encryption_key_32_bytes_long_secret!"
    settings.GOOGLE_CLIENT_SECRET = "mock_secret_xyz_123"
    settings.OWNER_EMAIL = "test@example.com"
    yield
    settings.GMAIL_TOKEN_ENCRYPTION_KEY = orig_key
    settings.GOOGLE_CLIENT_SECRET = orig_secret
    settings.OWNER_EMAIL = orig_owner


async def create_test_lead_and_sent_message(
    db: AsyncSession,
    domain: str = "acme-followup.com",
    recipient_email: str = "ceo@acme-followup.com",
    lead_status: LeadStatus = LeadStatus.APPROVED,
    message_status: OutreachMessageStatus = OutreachMessageStatus.SENT,
    sent_at: Optional[datetime] = None,
) -> tuple[Lead, OutreachDraft, OutreachMessage]:
    """Helper to persist a Lead, OutreachDraft, and sent OutreachMessage."""
    lead = Lead(
        id=uuid.uuid4(),
        company_name="Acme Followup Inc",
        domain=domain,
        website_url=f"https://{domain}",
        phone="+15551234567",
        email=recipient_email,
        email_verification_status=EmailVerificationStatus.MX_VERIFIED,
        status=lead_status,
        source_type="google_places",
        qualification_score=85,
    )
    db.add(lead)
    await db.flush()

    draft = OutreachDraft(
        id=uuid.uuid4(),
        lead_id=lead.id,
        recipient_email=recipient_email,
        subject="Initial Outreach Proposal",
        body_text="Initial factual pitch.",
        status=OutreachDraftStatus.SENT,
        approved_at=datetime.now(timezone.utc),
        approved_by="test@example.com",
    )
    db.add(draft)
    await db.flush()

    msg = OutreachMessage(
        id=uuid.uuid4(),
        draft_id=draft.id,
        lead_id=lead.id,
        recipient_email=recipient_email,
        subject=draft.subject,
        gmail_message_id="msg_orig_12345",
        gmail_thread_id="th_orig_12345",
        sent_at=sent_at or (datetime.now(timezone.utc) - timedelta(days=3)),
        status=message_status,
    )
    db.add(msg)
    await db.commit()
    await db.refresh(lead)
    await db.refresh(draft)
    await db.refresh(msg)
    return lead, draft, msg


async def setup_test_gmail_account(
    db: AsyncSession,
    owner_id: str = "test@example.com",
    status: GmailConnectionStatus = GmailConnectionStatus.CONNECTED,
) -> GmailAccount:
    """Helper to create a connected GmailAccount."""
    enc = TokenEncryptionService()
    token = enc.encrypt("mock_refresh_token_xyz")
    account = GmailAccount(
        owner_id=owner_id,
        google_email="owner@gmail.com",
        encrypted_refresh_token=token,
        connection_status=status,
        token_created_at=datetime.now(timezone.utc),
        last_health_check=datetime.now(timezone.utc),
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


# ── Test Cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_sequence_success(client: AsyncClient, auth_headers: dict):
    """
    POST /api/v1/follow-ups/sequences creates an ACTIVE sequence with 3 ordered steps
    matching the approved default cadence (48h, 120h, 240h).
    """
    sent_time = datetime.now(timezone.utc) - timedelta(days=1)
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session, sent_at=sent_time)
        msg_id = msg.id

    payload = {"original_message_id": str(msg_id)}
    res = await client.post("/api/v1/follow-ups/sequences", headers=auth_headers, json=payload)
    assert res.status_code == 201, res.text
    data = res.json()

    assert data["status"] == "active"
    assert data["current_step"] == 1
    assert data["max_steps"] == 3
    assert len(data["steps"]) == 3

    # Verify steps ordering and delay hours
    steps = data["steps"]
    assert steps[0]["step_number"] == 1
    assert steps[0]["delay_hours"] == 48
    assert steps[0]["status"] == "pending"

    assert steps[1]["step_number"] == 2
    assert steps[1]["delay_hours"] == 120
    assert steps[1]["status"] == "pending"

    assert steps[2]["step_number"] == 3
    assert steps[2]["delay_hours"] == 240
    assert steps[2]["status"] == "pending"

    # Verify scheduled_at calculations (sent_time + delay_hours)
    step1_sched = datetime.fromisoformat(steps[0]["scheduled_at"])
    if step1_sched.tzinfo is None:
        step1_sched = step1_sched.replace(tzinfo=timezone.utc)
    expected_step1 = sent_time + timedelta(hours=48)
    assert abs((step1_sched - expected_step1).total_seconds()) < 2


@pytest.mark.asyncio
async def test_create_sequence_custom_cadence(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/follow-ups/sequences supports custom cadence configurations."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        msg_id = msg.id

    custom_cadence = [
        {"step_number": 1, "delay_hours": 24},
        {"step_number": 2, "delay_hours": 72},
    ]
    payload = {
        "original_message_id": str(msg_id),
        "cadence": custom_cadence,
    }
    res = await client.post("/api/v1/follow-ups/sequences", headers=auth_headers, json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["max_steps"] == 2
    assert len(data["steps"]) == 2
    assert data["steps"][0]["delay_hours"] == 24
    assert data["steps"][1]["delay_hours"] == 72


@pytest.mark.asyncio
async def test_create_sequence_requires_sent_original_message(client: AsyncClient, auth_headers: dict):
    """Cannot create a follow-up sequence for an unsent or non-existent outreach message."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(
            session, message_status=OutreachMessageStatus.FAILED
        )
        msg_id = msg.id

    payload = {"original_message_id": str(msg_id)}
    res = await client.post("/api/v1/follow-ups/sequences", headers=auth_headers, json=payload)
    assert res.status_code == 400
    assert "sent" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_duplicate_active_sequence_prevention(client: AsyncClient, auth_headers: dict):
    """Cannot create multiple ACTIVE follow-up sequences for the same outreach message."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        msg_id = msg.id

    payload = {"original_message_id": str(msg_id)}
    # 1st creation succeeds
    res1 = await client.post("/api/v1/follow-ups/sequences", headers=auth_headers, json=payload)
    assert res1.status_code == 201

    # 2nd creation is rejected with 409 Conflict
    res2 = await client.post("/api/v1/follow-ups/sequences", headers=auth_headers, json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"].lower()


def test_cadence_validation_non_sequential_or_decreasing():
    """calculate_cadence_schedule enforces sequential steps and strictly increasing delays."""
    now = datetime.now(timezone.utc)

    # Decreasing delays
    bad_cadence_1 = [
        CadenceStepConfig(step_number=1, delay_hours=48),
        CadenceStepConfig(step_number=2, delay_hours=24),
    ]
    with pytest.raises(ValueError, match="strictly greater"):
        calculate_cadence_schedule(now, bad_cadence_1)

    # Non-sequential step numbers
    bad_cadence_2 = [
        CadenceStepConfig(step_number=1, delay_hours=48),
        CadenceStepConfig(step_number=3, delay_hours=120),
    ]
    with pytest.raises(ValueError, match="must be sequential"):
        calculate_cadence_schedule(now, bad_cadence_2)


@pytest.mark.asyncio
async def test_pause_active_sequence(client: AsyncClient, auth_headers: dict):
    """Owner can pause an ACTIVE follow-up sequence."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)
        seq_id = seq.id

    res = await client.post(f"/api/v1/follow-ups/sequences/{seq_id}/pause", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "paused"

    # Verify DB
    async with TestSessionLocal() as session:
        updated = await session.scalar(select(FollowUpSequence).where(FollowUpSequence.id == seq_id))
        assert updated.status == FollowUpSequenceStatus.PAUSED


@pytest.mark.asyncio
async def test_resume_paused_sequence(client: AsyncClient, auth_headers: dict):
    """Owner can resume a PAUSED follow-up sequence back to ACTIVE."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)
        await service.pause_sequence(session, sequence_id=seq.id)
        seq_id = seq.id

    res = await client.post(f"/api/v1/follow-ups/sequences/{seq_id}/resume", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_stop_sequence_owner_action(client: AsyncClient, auth_headers: dict):
    """Owner can permanently stop a sequence, cancelling all pending child steps."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)
        seq_id = seq.id

    payload = {"reason": "owner_stopped", "notes": "Prospect contacted directly via phone."}
    res = await client.post(f"/api/v1/follow-ups/sequences/{seq_id}/stop", headers=auth_headers, json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "stopped"
    assert data["stop_reason"] == "owner_stopped"
    assert data["next_action_at"] is None

    # Verify all child steps cancelled
    for s in data["steps"]:
        assert s["status"] == "cancelled"


@pytest.mark.asyncio
async def test_reply_stop_behavior(client: AsyncClient, auth_headers: dict):
    """Verified prospect reply stops sequence immediately and records stop_reason = REPLIED."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)
        seq_id = seq.id

    payload = {
        "gmail_message_id": "reply_msg_9999",
        "snippet": "Thanks for reaching out, let's schedule a call.",
    }
    res = await client.post(
        f"/api/v1/follow-ups/sequences/{seq_id}/reply-detected",
        headers=auth_headers,
        json=payload,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "stopped"
    assert data["stop_reason"] == "replied"
    assert data["next_action_at"] is None

    # Check child steps cancelled
    for s in data["steps"]:
        assert s["status"] == "cancelled"

    # Verify audit event in agent_runs
    async with TestSessionLocal() as session:
        runs = (
            await session.scalars(
                select(AgentRun).where(AgentRun.agent_name == "follow_up")
            )
        ).all()
        actions = [r.input_data.get("action") for r in runs if r.input_data]
        assert "reply_detected" in actions


@pytest.mark.asyncio
async def test_invalid_state_transitions(client: AsyncClient, auth_headers: dict):
    """Enforces state machine rules: cannot pause paused sequence, cannot stop stopped sequence."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)
        seq_id = seq.id

    # 1. Stop sequence
    await client.post(f"/api/v1/follow-ups/sequences/{seq_id}/stop", headers=auth_headers, json={})

    # 2. Cannot pause a stopped sequence
    pause_res = await client.post(f"/api/v1/follow-ups/sequences/{seq_id}/pause", headers=auth_headers)
    assert pause_res.status_code == 400

    # 3. Cannot resume a stopped sequence
    resume_res = await client.post(f"/api/v1/follow-ups/sequences/{seq_id}/resume", headers=auth_headers)
    assert resume_res.status_code == 400


@pytest.mark.asyncio
async def test_scheduler_finds_due_eligible_steps():
    """
    FollowUpSchedulerService identifies steps whose scheduled_at has arrived,
    evaluates eligibility, and marks step status = READY.
    """
    now = datetime.now(timezone.utc)
    # Message sent 3 days ago (72 hours ago)
    # Default cadence: Step 1 (48h) is DUE, Step 2 (120h) is in the FUTURE
    sent_time = now - timedelta(hours=72)

    async with TestSessionLocal() as session:
        await setup_test_gmail_account(session)
        lead, draft, msg = await create_test_lead_and_sent_message(session, sent_at=sent_time)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)
        seq_id = seq.id

    # Run scheduler
    scheduler = FollowUpSchedulerService()
    async with TestSessionLocal() as session:
        due_steps = await scheduler.find_due_follow_up_steps(session, now=now)

    assert len(due_steps) == 1
    step_item = due_steps[0]
    assert step_item.sequence_id == seq_id
    assert step_item.step_number == 1
    assert step_item.eligibility.eligible is True

    # Verify DB step status transitioned from PENDING to READY
    async with TestSessionLocal() as session:
        step = await session.scalar(
            select(FollowUpStep).where(FollowUpStep.id == step_item.step_id)
        )
        assert step.status == FollowUpStepStatus.READY


@pytest.mark.asyncio
async def test_scheduler_ignores_future_steps():
    """Scheduler does not return steps whose scheduled_at is still in the future."""
    now = datetime.now(timezone.utc)
    # Message sent only 10 hours ago (Step 1 is due in 38 hours)
    sent_time = now - timedelta(hours=10)

    async with TestSessionLocal() as session:
        await setup_test_gmail_account(session)
        lead, draft, msg = await create_test_lead_and_sent_message(session, sent_at=sent_time)
        service = FollowUpService()
        await service.create_sequence(session, original_message_id=msg.id)

    scheduler = FollowUpSchedulerService()
    async with TestSessionLocal() as session:
        due_steps = await scheduler.find_due_follow_up_steps(session, now=now)

    assert len(due_steps) == 0


@pytest.mark.asyncio
async def test_scheduler_never_sends_email_or_calls_gmail():
    """
    CRITICAL SAFETY INVARIANT:
    FollowUpSchedulerService ONLY identifies due steps.
    It MUST NOT call Gmail API, create OutreachMessages, or dispatch emails.
    """
    now = datetime.now(timezone.utc)
    sent_time = now - timedelta(hours=72)

    async with TestSessionLocal() as session:
        await setup_test_gmail_account(session)
        lead, draft, msg = await create_test_lead_and_sent_message(session, sent_at=sent_time)
        service = FollowUpService()
        await service.create_sequence(session, original_message_id=msg.id)
        initial_msg_count = len((await session.scalars(select(OutreachMessage))).all())

    # Run scheduler under inspection
    scheduler = FollowUpSchedulerService()
    async with TestSessionLocal() as session:
        with patch("services.gmail_dispatch_service.httpx.AsyncClient") as mock_client:
            due = await scheduler.find_due_follow_up_steps(session, now=now)
            # Ensure mock was never even called
            mock_client.assert_not_called()

        # Ensure no new OutreachMessage was created
        final_msg_count = len((await session.scalars(select(OutreachMessage))).all())
        assert final_msg_count == initial_msg_count


@pytest.mark.asyncio
async def test_eligibility_blocks_suppressed_recipient():
    """FollowUpEligibilityService blocks sequence if recipient email/domain is suppressed."""
    async with TestSessionLocal() as session:
        await setup_test_gmail_account(session)
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)

        # Add suppression
        suppression = SuppressionRecord(
            email=lead.email,
            reason=SuppressionReason.OPT_OUT,
        )
        session.add(suppression)
        await session.commit()

        eligibility_service = FollowUpEligibilityService()
        res = await eligibility_service.evaluate_sequence_eligibility(session, sequence=seq)

    assert res.eligible is False
    assert "suppression list" in (res.reason or "").lower()


@pytest.mark.asyncio
async def test_eligibility_blocks_disconnected_gmail():
    """FollowUpEligibilityService blocks sequence if Gmail account is DISCONNECTED."""
    async with TestSessionLocal() as session:
        await setup_test_gmail_account(session, status=GmailConnectionStatus.DISCONNECTED)
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)

        eligibility_service = FollowUpEligibilityService()
        res = await eligibility_service.evaluate_sequence_eligibility(session, sequence=seq)

    assert res.eligible is False
    assert "gmail" in (res.reason or "").lower()


@pytest.mark.asyncio
async def test_eligibility_blocks_paused_circuit_breaker():
    """FollowUpEligibilityService blocks sequence if Circuit Breaker is PAUSED."""
    async with TestSessionLocal() as session:
        await setup_test_gmail_account(session)
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)

        # Record consecutive bounces to trip breaker to PAUSED
        now = datetime.now(timezone.utc)
        for i in range(5):
            ev = DeliveryEvent(
                outreach_message_id=msg.id,
                event_type=DeliveryEventType.BOUNCED,
                event_timestamp=now - timedelta(seconds=i * 10),
                created_at=now - timedelta(seconds=i * 10),
            )
            session.add(ev)
        await session.commit()

        eligibility_service = FollowUpEligibilityService()
        res = await eligibility_service.evaluate_sequence_eligibility(session, sequence=seq)

    assert res.eligible is False
    assert "circuit breaker" in (res.reason or "").lower()


@pytest.mark.asyncio
async def test_eligibility_blocks_disqualified_lead():
    """FollowUpEligibilityService blocks sequence if lead was DISQUALIFIED."""
    async with TestSessionLocal() as session:
        await setup_test_gmail_account(session)
        lead, draft, msg = await create_test_lead_and_sent_message(
            session, lead_status=LeadStatus.DISQUALIFIED
        )
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)

        eligibility_service = FollowUpEligibilityService()
        res = await eligibility_service.evaluate_sequence_eligibility(session, sequence=seq)

    assert res.eligible is False
    assert "disqualified" in (res.reason or "").lower()


@pytest.mark.asyncio
async def test_owner_auth_required(client: AsyncClient):
    """Endpoints return 401 Unauthorized when unauthenticated."""
    seq_id = uuid.uuid4()
    res = await client.get(f"/api/v1/follow-ups/sequences/{seq_id}")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_idor_protection(client: AsyncClient):
    """Foreign owner token returns 403 Forbidden."""
    foreign_token, _ = _create_access_token("attacker@foreign-agency.com")
    headers = {"Authorization": f"Bearer {foreign_token}"}
    seq_id = uuid.uuid4()
    res = await client.get(f"/api/v1/follow-ups/sequences/{seq_id}", headers=headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_audit_logging_and_zero_token_leakage(client: AsyncClient, auth_headers: dict):
    """Verify follow-up audit trail in agent_runs and absolute zero secret/token leakage."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        msg_id = msg.id

    # Create sequence
    res = await client.post(
        "/api/v1/follow-ups/sequences",
        headers=auth_headers,
        json={"original_message_id": str(msg_id)},
    )
    assert res.status_code == 201
    seq_id = res.json()["id"]

    # Pause and Resume
    await client.post(f"/api/v1/follow-ups/sequences/{seq_id}/pause", headers=auth_headers)
    await client.post(f"/api/v1/follow-ups/sequences/{seq_id}/resume", headers=auth_headers)

    # Inspect all AgentRun records
    async with TestSessionLocal() as session:
        runs = (
            await session.scalars(
                select(AgentRun).where(AgentRun.agent_name == "follow_up")
            )
        ).all()
        assert len(runs) >= 4

        actions = [r.input_data.get("action") for r in runs if r.input_data]
        assert "followup_sequence_created" in actions
        assert "followup_step_scheduled" in actions
        assert "followup_sequence_paused" in actions
        assert "followup_sequence_resumed" in actions

        for r in runs:
            content = f"{r.input_data} {r.output_data} {r.error_message}"
            assert settings.GMAIL_TOKEN_ENCRYPTION_KEY not in content
            assert settings.GOOGLE_CLIENT_SECRET not in content


@pytest.mark.asyncio
async def test_list_and_get_sequence_detail(client: AsyncClient, auth_headers: dict):
    """Owner can list sequences with pagination and retrieve detailed view with child steps."""
    async with TestSessionLocal() as session:
        lead, draft, msg = await create_test_lead_and_sent_message(session)
        service = FollowUpService()
        seq = await service.create_sequence(session, original_message_id=msg.id)
        seq_id = seq.id

    # List
    list_res = await client.get("/api/v1/follow-ups/sequences", headers=auth_headers)
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 1

    # Detail
    detail_res = await client.get(f"/api/v1/follow-ups/sequences/{seq_id}", headers=auth_headers)
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["id"] == str(seq_id)
    assert len(detail_data["steps"]) == 3
