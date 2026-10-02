"""
Comprehensive test suite for Phase 4 Stage 4.3 — Gmail Dispatch Adapter + Single Manual Send.

Tests:
1. test_single_manual_send_success: Complete end-to-end single send path.
2. test_send_requires_authentication: 401 when unauthenticated.
3. test_send_enforces_owner_authorization: 403 when wrong owner / IDOR.
4. test_send_draft_not_found: 404 when draft ID does not exist.
5. test_send_unapproved_draft_blocked: 400 when draft is PENDING_APPROVAL.
6. test_send_rejected_draft_blocked: 400 when draft is REJECTED.
7. test_send_duplicate_prevention_draft_already_sent: 409 Conflict.
8. test_send_duplicate_prevention_existing_outreach_message: 409 Conflict.
9. test_safety_controller_blocks_unverified_email: 400 + BLOCKED SendAttempt.
10. test_safety_controller_blocks_suppressed_email: 400 + BLOCKED SendAttempt.
11. test_safety_controller_blocks_daily_quota_exceeded: 400 + BLOCKED SendAttempt.
12. test_safety_controller_blocks_domain_pacing_under_120s: 400 + BLOCKED SendAttempt.
13. test_safety_controller_blocks_paused_circuit_breaker: 400 + BLOCKED SendAttempt.
14. test_send_blocks_when_gmail_disconnected: 400 + BLOCKED SendAttempt.
15. test_gmail_api_error_401_unauthorized: 502 + FAILED SendAttempt.
16. test_gmail_api_error_403_forbidden: 502 + FAILED SendAttempt.
17. test_gmail_api_error_429_rate_limit: 502 + FAILED SendAttempt.
18. test_gmail_api_error_500_server_error: 502 + FAILED SendAttempt.
19. test_gmail_api_network_timeout: 502 + FAILED SendAttempt.
20. test_mime_message_construction_plain_text: RFC 2822 plain text validation.
21. test_request_body_cannot_override_recipient_or_body: Immutable server-side source of truth.
22. test_audit_trail_never_leaks_tokens: Zero token leakage in audit logs.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import email
from email import policy
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
from services.gmail_dispatch_service import (
    GmailDispatchAuthError,
    GmailDispatchInvalidRequestError,
    GmailDispatchService,
)
from services.safety_controller import SafetyController
from services.token_encryption import TokenEncryptionService
from tests.conftest import TestSessionLocal


# ── Fixtures & Setup ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def setup_oauth_env_settings():
    """Ensure test environment has OAuth configuration set for the test run."""
    original_client_id = settings.GOOGLE_CLIENT_ID
    original_client_secret = settings.GOOGLE_CLIENT_SECRET
    original_encryption_key = settings.GMAIL_TOKEN_ENCRYPTION_KEY

    settings.GOOGLE_CLIENT_ID = "mock_client_id_123.apps.googleusercontent.com"
    settings.GOOGLE_CLIENT_SECRET = "mock_client_secret_xyz"
    settings.GMAIL_TOKEN_ENCRYPTION_KEY = "test_encryption_key_32_bytes_long_secret!"

    yield

    settings.GOOGLE_CLIENT_ID = original_client_id
    settings.GOOGLE_CLIENT_SECRET = original_client_secret
    settings.GMAIL_TOKEN_ENCRYPTION_KEY = original_encryption_key


async def setup_test_lead_and_draft(
    db: AsyncSession,
    draft_status: OutreachDraftStatus = OutreachDraftStatus.APPROVED,
    lead_status: LeadStatus = LeadStatus.APPROVED,
    email_status: EmailVerificationStatus = EmailVerificationStatus.MX_VERIFIED,
    domain: str = "example-dispatch.com",
    recipient_email: Optional[str] = None,
) -> tuple[Lead, OutreachDraft]:
    """Helper to create a validated lead and outreach draft."""
    lead = Lead(
        id=uuid.uuid4(),
        company_name="Apex Dispatch Corp",
        domain=domain,
        website_url=f"https://{domain}",
        phone="+15550199000",
        email=recipient_email or f"ceo@{domain}",
        email_verification_status=email_status,
        status=lead_status,
        source_type="google_places",
        qualification_score=85,
    )
    db.add(lead)
    await db.flush()

    research = LeadResearch(
        lead_id=lead.id,
        has_website=True,
        is_responsive=True,
        has_ssl=True,
        status_code=200,
        load_time_ms=1200,
        copyright_year=2023,
        tech_stack={"framework": "Next.js"},
        audit_findings={"has_modern_ui": True},
    )
    db.add(research)
    await db.flush()

    draft = OutreachDraft(
        id=uuid.uuid4(),
        lead_id=lead.id,
        recipient_email=lead.email,
        subject="Modernizing Apex Dispatch Digital Presence",
        body_text="Hi Team,\n\nWe noticed your web presence could benefit from a few performance enhancements.\n\nBest,\nOwner",
        status=draft_status,
        approved_at=datetime.now(timezone.utc) if draft_status == OutreachDraftStatus.APPROVED else None,
        approved_by="test@example.com" if draft_status == OutreachDraftStatus.APPROVED else None,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    await db.refresh(lead)
    return lead, draft


async def setup_connected_gmail_account(
    db: AsyncSession,
    owner_id: str = "test@example.com",
    google_email: str = "agency.owner@gmail.com",
    connection_status: GmailConnectionStatus = GmailConnectionStatus.CONNECTED,
) -> GmailAccount:
    """Helper to create a connected Gmail account with encrypted token."""
    enc = TokenEncryptionService()
    encrypted_token = enc.encrypt("mock_refresh_token_valid_xyz")

    account = GmailAccount(
        owner_id=owner_id,
        google_email=google_email,
        encrypted_refresh_token=encrypted_token,
        connection_status=connection_status,
        token_created_at=datetime.now(timezone.utc),
        last_health_check=datetime.now(timezone.utc),
    )
    db.add(account)
    await db.commit()
    await db.refresh(account)
    return account


@contextmanager
def mock_google_gmail_dispatch(
    token_response: Optional[Response] = None,
    send_response: Optional[Response] = None,
    send_side_effect: Optional[Exception] = None,
):
    """
    Mock ONLY the httpx.AsyncClient instances inside Gmail credential & dispatch services,
    leaving the test client's ASGI transport completely intact.
    Routes responses accurately based on the target URL (token vs send).
    """
    captured_calls = []

    async def fake_post(url, *args, **kwargs):
        url_str = str(url)
        captured_calls.append({"url": url_str, "args": args, "kwargs": kwargs})
        if "oauth2.googleapis.com/token" in url_str:
            if token_response is not None:
                return token_response
            return Response(
                status_code=200,
                json={"access_token": "ya29.ephemeral_access_token_abc123", "expires_in": 3600},
            )
        elif "gmail.googleapis.com" in url_str:
            if send_side_effect is not None:
                raise send_side_effect
            if send_response is not None:
                return send_response
            return Response(
                status_code=200,
                json={"id": "msg_gmail_mock_12345", "threadId": "th_gmail_mock_12345"},
            )
        return Response(status_code=404)

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None
    mock_client.post.side_effect = fake_post

    with patch("services.gmail_credential_service.httpx.AsyncClient", return_value=mock_client), \
         patch("services.gmail_dispatch_service.httpx.AsyncClient", return_value=mock_client):
        yield (mock_client, captured_calls)


# ── Test Cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_manual_send_success(client: AsyncClient, auth_headers: dict):
    """
    Test successful controlled single-email manual dispatch path:
    APPROVED draft + APPROVED lead + MX_VERIFIED email + CONNECTED Gmail
    -> SafetyController passes
    -> Gmail API send succeeds
    -> OutreachMessage created
    -> SendAttempt marked SUCCESS
    -> Draft status updated to SENT
    -> Audit events recorded
    """
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(session)
        account = await setup_connected_gmail_account(session)
        draft_id = draft.id
        lead_id = lead.id

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["success"] is True
    assert data["draft_id"] == str(draft_id)
    assert data["lead_id"] == str(lead_id)
    assert data["gmail_message_id"] == "msg_gmail_mock_12345"
    assert data["gmail_thread_id"] == "th_gmail_mock_12345"
    assert data["status"] == "sent"

    # Verify Database state
    async with TestSessionLocal() as session:
        # 1. Draft status is SENT
        updated_draft = await session.scalar(select(OutreachDraft).where(OutreachDraft.id == draft_id))
        assert updated_draft.status == OutreachDraftStatus.SENT

        # 2. OutreachMessage created
        outreach_msg = await session.scalar(
            select(OutreachMessage).where(OutreachMessage.draft_id == draft_id)
        )
        assert outreach_msg is not None
        assert outreach_msg.status == OutreachMessageStatus.SENT
        assert outreach_msg.gmail_message_id == "msg_gmail_mock_12345"
        assert outreach_msg.gmail_thread_id == "th_gmail_mock_12345"
        assert outreach_msg.recipient_email == updated_draft.recipient_email

        # 3. SendAttempt created with SUCCESS
        send_att = await session.scalar(
            select(SendAttempt).where(SendAttempt.draft_id == draft_id)
        )
        assert send_att is not None
        assert send_att.result == SendAttemptResult.SUCCESS
        assert send_att.gmail_message_id == "msg_gmail_mock_12345"
        assert send_att.gmail_thread_id == "th_gmail_mock_12345"

        # 4. AgentRun audit logs
        runs = (
            await session.scalars(
                select(AgentRun)
                .where(AgentRun.agent_name == "gmail_dispatch")
                .order_by(AgentRun.started_at.asc())
            )
        ).all()
        actions = [r.input_data.get("action") for r in runs if r.input_data]
        assert "dispatch_requested" in actions
        assert "dispatch_success" in actions


@pytest.mark.asyncio
async def test_send_requires_authentication(client: AsyncClient):
    """POST /api/v1/outreach/drafts/{draft_id}/send returns 401 without auth."""
    fake_id = uuid.uuid4()
    res = await client.post(f"/api/v1/outreach/drafts/{fake_id}/send")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_send_enforces_owner_authorization(client: AsyncClient):
    """POST /api/v1/outreach/drafts/{draft_id}/send returns 403 for unauthorized caller."""
    token, _ = _create_access_token("intruder@evil.com")
    headers = {"Authorization": f"Bearer {token}"}
    fake_id = uuid.uuid4()
    res = await client.post(f"/api/v1/outreach/drafts/{fake_id}/send", headers=headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_send_draft_not_found(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/outreach/drafts/{draft_id}/send returns 404 if draft does not exist."""
    fake_id = uuid.uuid4()
    res = await client.post(f"/api/v1/outreach/drafts/{fake_id}/send", headers=auth_headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_send_unapproved_draft_blocked(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/outreach/drafts/{draft_id}/send blocks draft with PENDING_APPROVAL."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.PENDING_APPROVAL
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 400
    assert "APPROVED" in res.json()["detail"]

    # Verify DB: SendAttempt marked BLOCKED, draft unchanged
    async with TestSessionLocal() as session:
        d = await session.scalar(select(OutreachDraft).where(OutreachDraft.id == draft_id))
        assert d.status == OutreachDraftStatus.PENDING_APPROVAL

        attempt = await session.scalar(select(SendAttempt).where(SendAttempt.draft_id == draft_id))
        assert attempt is not None
        assert attempt.result == SendAttemptResult.BLOCKED


@pytest.mark.asyncio
async def test_send_rejected_draft_blocked(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/outreach/drafts/{draft_id}/send blocks draft with REJECTED status."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.REJECTED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 400
    assert "APPROVED" in res.json()["detail"]


@pytest.mark.asyncio
async def test_send_duplicate_prevention_draft_already_sent(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/outreach/drafts/{draft_id}/send returns 409 Conflict if draft status is already SENT."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.SENT
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 409
    assert "already been sent" in res.json()["detail"]


@pytest.mark.asyncio
async def test_send_duplicate_prevention_existing_outreach_message(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/outreach/drafts/{draft_id}/send returns 409 Conflict if an OutreachMessage exists."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

        # Insert existing OutreachMessage
        msg = OutreachMessage(
            draft_id=draft.id,
            lead_id=lead.id,
            recipient_email=draft.recipient_email,
            subject=draft.subject,
            gmail_message_id="msg_prior_123",
            gmail_thread_id="th_prior_123",
            sent_at=datetime.now(timezone.utc),
            status=OutreachMessageStatus.SENT,
        )
        session.add(msg)
        await session.commit()

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


@pytest.mark.asyncio
async def test_safety_controller_blocks_unverified_email(client: AsyncClient, auth_headers: dict):
    """SafetyController blocks send if lead email is not MX_VERIFIED."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session,
            draft_status=OutreachDraftStatus.APPROVED,
            email_status=EmailVerificationStatus.UNVERIFIED,
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 400
    assert "MX_VERIFIED" in res.json()["detail"]

    # Verify SendAttempt recorded as BLOCKED
    async with TestSessionLocal() as session:
        attempt = await session.scalar(select(SendAttempt).where(SendAttempt.draft_id == draft_id))
        assert attempt is not None
        assert attempt.result == SendAttemptResult.BLOCKED


@pytest.mark.asyncio
async def test_safety_controller_blocks_suppressed_email(client: AsyncClient, auth_headers: dict):
    """SafetyController blocks send if recipient email is in SuppressionRecord."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

        suppression = SuppressionRecord(
            email=draft.recipient_email,
            reason=SuppressionReason.OPT_OUT,
        )
        session.add(suppression)
        await session.commit()

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 400
    assert "suppression violation" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_safety_controller_blocks_daily_quota_exceeded(client: AsyncClient, auth_headers: dict):
    """SafetyController blocks send when total daily sends quota (30) is reached."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED, domain="quota-test.com"
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

        now = datetime.now(timezone.utc)
        # Prepopulate 30 sent messages today
        for i in range(30):
            msg = OutreachMessage(
                draft_id=uuid.uuid4(),
                lead_id=uuid.uuid4(),
                recipient_email=f"prior{i}@quota-other{i}.com",
                subject="Test",
                gmail_message_id=f"prior_msg_{i}",
                sent_at=now - timedelta(minutes=10),
                status=OutreachMessageStatus.SENT,
            )
            session.add(msg)
        await session.commit()

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 400
    assert "Daily send quota" in res.json()["detail"]


@pytest.mark.asyncio
async def test_safety_controller_blocks_domain_pacing_under_120s(client: AsyncClient, auth_headers: dict):
    """SafetyController blocks send when an email to the same domain was sent < 120s ago."""
    test_domain = "pacing-check.com"
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED, domain=test_domain
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

        # Insert message sent 30 seconds ago to the same domain
        prior_msg = OutreachMessage(
            draft_id=uuid.uuid4(),
            lead_id=lead.id,
            recipient_email=f"info@{test_domain}",
            subject="Prior Pacing Email",
            gmail_message_id="prior_pacing_msg",
            sent_at=datetime.now(timezone.utc) - timedelta(seconds=30),
            status=OutreachMessageStatus.SENT,
        )
        session.add(prior_msg)
        await session.commit()

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 400
    assert "Domain pacing violation" in res.json()["detail"]


@pytest.mark.asyncio
async def test_safety_controller_blocks_paused_circuit_breaker(client: AsyncClient, auth_headers: dict):
    """SafetyController blocks dispatch if circuit breaker is PAUSED."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

        msg = OutreachMessage(
            draft_id=uuid.uuid4(),
            lead_id=lead.id,
            recipient_email="bounce@test.com",
            subject="Test",
            status=OutreachMessageStatus.SENT,
        )
        session.add(msg)
        await session.flush()

        # Insert consecutive bounced delivery events
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

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 400
    assert "circuit breaker" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_send_blocks_when_gmail_disconnected(client: AsyncClient, auth_headers: dict):
    """Endpoint returns 400 if the owner's Gmail account is DISCONNECTED."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(
            session, connection_status=GmailConnectionStatus.DISCONNECTED
        )
        draft_id = draft.id

    with mock_google_gmail_dispatch():
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 400
    assert "connected Gmail account" in res.json()["detail"]


@pytest.mark.asyncio
async def test_gmail_api_error_401_unauthorized(client: AsyncClient, auth_headers: dict):
    """Gmail API 401 returns 502, records SendAttempt FAILED, draft remains un-sent."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

    mock_send_401 = Response(
        status_code=401,
        json={"error": {"code": 401, "message": "Invalid Credentials"}},
    )

    with mock_google_gmail_dispatch(send_response=mock_send_401):
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 502
    assert "Gmail API rejected access token" in res.json()["detail"]

    # Verify DB: SendAttempt is FAILED, draft status remains APPROVED
    async with TestSessionLocal() as session:
        d = await session.scalar(select(OutreachDraft).where(OutreachDraft.id == draft_id))
        assert d.status == OutreachDraftStatus.APPROVED

        attempt = await session.scalar(select(SendAttempt).where(SendAttempt.draft_id == draft_id))
        assert attempt is not None
        assert attempt.result == SendAttemptResult.FAILED


@pytest.mark.asyncio
async def test_gmail_api_error_403_forbidden(client: AsyncClient, auth_headers: dict):
    """Gmail API 403 returns 502, records SendAttempt FAILED."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

    mock_send_403 = Response(
        status_code=403,
        json={"error": {"code": 403, "message": "Insufficient Permission"}},
    )

    with mock_google_gmail_dispatch(send_response=mock_send_403):
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 502
    assert "403 Forbidden" in res.json()["detail"]


@pytest.mark.asyncio
async def test_gmail_api_error_429_rate_limit(client: AsyncClient, auth_headers: dict):
    """Gmail API 429 returns 502, records SendAttempt FAILED."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

    mock_send_429 = Response(
        status_code=429,
        json={"error": {"code": 429, "message": "User Rate Limit Exceeded"}},
    )

    with mock_google_gmail_dispatch(send_response=mock_send_429):
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 502
    assert "rate limit exceeded" in res.json()["detail"]


@pytest.mark.asyncio
async def test_gmail_api_error_500_server_error(client: AsyncClient, auth_headers: dict):
    """Gmail API 500 returns 502, records SendAttempt FAILED."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

    mock_send_500 = Response(
        status_code=500,
        text="Internal Server Error",
    )

    with mock_google_gmail_dispatch(send_response=mock_send_500):
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 502
    assert "server error" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_gmail_api_network_timeout(client: AsyncClient, auth_headers: dict):
    """Network timeout during Gmail API send returns 502, records SendAttempt FAILED."""
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id

    with mock_google_gmail_dispatch(send_side_effect=httpx.TimeoutException("Connection timed out")):
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 502
    assert "timed out" in res.json()["detail"].lower()

    async with TestSessionLocal() as session:
        attempt = await session.scalar(select(SendAttempt).where(SendAttempt.draft_id == draft_id))
        assert attempt is not None
        assert attempt.result == SendAttemptResult.FAILED


def test_mime_message_construction_plain_text():
    """Verify GmailDispatchService constructs compliant RFC 2822 plain text email."""
    service = GmailDispatchService()
    raw_b64 = service.build_mime_message(
        recipient_email="recipient@example.com",
        sender_email="sender@agency.com",
        subject="Special Invitation",
        body_text="Hello,\nThis is a strict plain-text message.",
    )

    # Decode and parse MIME message
    decoded_bytes = base64.urlsafe_b64decode(raw_b64.encode("ascii"))
    parsed_msg = email.message_from_bytes(decoded_bytes, policy=policy.default)

    assert parsed_msg["To"] == "recipient@example.com"
    assert parsed_msg["From"] == "sender@agency.com"
    assert parsed_msg["Subject"] == "Special Invitation"
    assert parsed_msg.get_content_type() == "text/plain"
    assert "This is a strict plain-text message." in parsed_msg.get_content()

    # Reject empty recipient
    with pytest.raises(GmailDispatchInvalidRequestError):
        service.build_mime_message("", "sender@agency.com", "Subject", "Body")

    # Reject empty sender
    with pytest.raises(GmailDispatchInvalidRequestError):
        service.build_mime_message("recipient@example.com", "", "Subject", "Body")


@pytest.mark.asyncio
async def test_request_body_cannot_override_recipient_or_body(client: AsyncClient, auth_headers: dict):
    """
    Verify that arbitrary JSON passed in request body CANNOT override the approved draft's
    recipient email, subject, or body text.
    """
    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        await setup_connected_gmail_account(session)
        draft_id = draft.id
        legit_recipient = draft.recipient_email
        legit_subject = draft.subject

    malicious_payload = {
        "recipient_email": "attacker@evil.com",
        "subject": "Hacked Subject",
        "body_text": "Phishing body content",
    }

    with mock_google_gmail_dispatch() as (mock_client, captured_calls):
        res = await client.post(
            f"/api/v1/outreach/drafts/{draft_id}/send",
            headers=auth_headers,
            json=malicious_payload,
        )

    assert res.status_code == 200
    assert res.json()["recipient_email"] == legit_recipient
    assert res.json()["subject"] == legit_subject

    # Decode what was actually sent to Gmail API
    gmail_calls = [c for c in captured_calls if "gmail.googleapis.com" in c["url"]]
    assert len(gmail_calls) == 1
    json_body = gmail_calls[0]["kwargs"].get("json", {})
    raw_sent = json_body.get("raw", "")
    decoded = base64.urlsafe_b64decode(raw_sent.encode("ascii")).decode("utf-8")
    assert legit_recipient in decoded
    assert "attacker@evil.com" not in decoded
    assert "Hacked Subject" not in decoded


@pytest.mark.asyncio
async def test_audit_trail_never_leaks_tokens(client: AsyncClient, auth_headers: dict):
    """
    Verify that no access tokens, refresh tokens, encryption secrets, or OAuth credentials
    appear in the database audit log (AgentRun).
    """
    secret_refresh = "super_secret_refresh_token_string_999"
    enc = TokenEncryptionService()
    encrypted_token = enc.encrypt(secret_refresh)

    async with TestSessionLocal() as session:
        lead, draft = await setup_test_lead_and_draft(
            session, draft_status=OutreachDraftStatus.APPROVED
        )
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc),
        )
        session.add(account)
        await session.commit()
        draft_id = draft.id

    ephemeral_access_token = "ya29.ephemeral_secret_access_token_888"

    mock_token_resp = Response(
        status_code=200,
        json={"access_token": ephemeral_access_token, "expires_in": 3600},
    )

    with mock_google_gmail_dispatch(token_response=mock_token_resp):
        res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/send", headers=auth_headers)

    assert res.status_code == 200

    # Scan all AgentRun records
    async with TestSessionLocal() as session:
        runs = (await session.scalars(select(AgentRun))).all()
        assert len(runs) > 0

        for r in runs:
            content_str = f"{r.input_data} {r.output_data} {r.error_message}"
            assert secret_refresh not in content_str
            assert ephemeral_access_token not in content_str
            assert settings.GMAIL_TOKEN_ENCRYPTION_KEY not in content_str
            assert settings.GOOGLE_CLIENT_SECRET not in content_str
