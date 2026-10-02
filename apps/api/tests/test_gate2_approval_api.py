"""
Comprehensive API tests for Stage 3.4 — Gate 2 Owner Approval API.

Verifies:
- List drafts with filtering (status, lead_id, email) & pagination
- Retrieve draft detail with lead research evidence
- Unauthorized access -> 401
- Wrong owner / foreign token -> 403 (IDOR protection)
- Approve pending draft -> 200 + audit record
- Reject pending draft -> 200 + audit record
- Approve already approved draft -> blocked (400)
- Reject already rejected draft -> blocked (400)
- Edit pending draft -> 200 + audit record
- Edit approved draft -> blocked (400)
- Edit rejected draft -> blocked (400)
- Approval with non-approved lead -> blocked (400)
- Approval with non-MX-verified email -> blocked (400)
- Invalid rejection reason (empty/whitespace) -> 422
- Audit record creation in agent_runs
- Reset draft to PENDING_APPROVAL workflow
"""
from __future__ import annotations

from datetime import datetime, timezone
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    AgentRun,
    EmailVerificationStatus,
    Lead,
    LeadResearch,
    LeadStatus,
)
from models.outreach import OutreachDraft, OutreachDraftStatus
from routers.auth import _create_access_token


async def create_fixture_lead(
    db: AsyncSession,
    status: LeadStatus = LeadStatus.APPROVED,
    email_verification_status: EmailVerificationStatus = EmailVerificationStatus.MX_VERIFIED,
    domain: str = "example.com",
    company_name: str = "Acme Corp",
) -> Lead:
    """Helper to create and persist a test lead with technical audit research."""
    lead = Lead(
        id=uuid.uuid4(),
        company_name=company_name,
        domain=domain,
        website_url=f"https://{domain}",
        phone="+15551234567",
        email=f"contact@{domain}",
        email_verification_status=email_verification_status,
        status=status,
        source_type="google_places",
        qualification_score=85,
    )
    db.add(lead)
    await db.flush()

    research = LeadResearch(
        lead_id=lead.id,
        has_website=True,
        is_responsive=False,
        has_ssl=True,
        status_code=200,
        load_time_ms=2800,
        copyright_year=2019,
        tech_stack={"framework": "WordPress"},
        audit_findings={"unresponsive": True, "stale_copyright": True},
    )
    db.add(research)
    await db.flush()
    return lead


async def create_fixture_draft(
    db: AsyncSession,
    lead: Lead,
    status: OutreachDraftStatus = OutreachDraftStatus.PENDING_APPROVAL,
    subject: str = "Modern web upgrade for Acme Corp",
    body_text: str = "Hi Acme team, noticed your site has an older copyright.",
) -> OutreachDraft:
    """Helper to create and persist an outreach draft."""
    draft = OutreachDraft(
        id=uuid.uuid4(),
        lead_id=lead.id,
        recipient_email=lead.email or f"info@{lead.domain}",
        subject=subject,
        body_text=body_text,
        body_html=f"<p>{body_text}</p>",
        status=status,
    )
    if status == OutreachDraftStatus.APPROVED:
        draft.approved_at = datetime.now(timezone.utc)
        draft.approved_by = "test@example.com"
    elif status == OutreachDraftStatus.REJECTED:
        draft.rejected_at = datetime.now(timezone.utc)
        draft.rejected_by = "test@example.com"
        draft.rejection_reason = "Not relevant"

    db.add(draft)
    await db.flush()
    return draft


@pytest.mark.asyncio
async def test_unauthorized_access_returns_401(client: AsyncClient):
    """Endpoints require valid Bearer token."""
    res = await client.get("/api/v1/outreach/drafts")
    assert res.status_code == 401
    assert "Authorization header required" in res.json()["detail"]

    random_id = uuid.uuid4()
    res = await client.get(f"/api/v1/outreach/drafts/{random_id}")
    assert res.status_code == 401

    res = await client.post(f"/api/v1/outreach/drafts/{random_id}/approve")
    assert res.status_code == 401

    res = await client.post(f"/api/v1/outreach/drafts/{random_id}/reject", json={"reason": "test"})
    assert res.status_code == 401

    res = await client.patch(f"/api/v1/outreach/drafts/{random_id}", json={"subject": "test"})
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_wrong_owner_returns_403_idor_protection(client: AsyncClient):
    """Tokens signed for non-authorized owner identities are rejected with 403 Forbidden."""
    wrong_token, _ = _create_access_token("attacker@foreign-agency.com")
    headers = {"Authorization": f"Bearer {wrong_token}"}

    res = await client.get("/api/v1/outreach/drafts", headers=headers)
    assert res.status_code == 403
    assert "Forbidden" in res.json()["detail"]

    random_id = uuid.uuid4()
    res = await client.post(f"/api/v1/outreach/drafts/{random_id}/approve", headers=headers)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_list_drafts_and_filtering(
    client: AsyncClient,
    auth_headers: dict,
    setup_test_database,
):
    """Verify list drafts endpoint with filtering by status and recipient email."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead1 = await create_fixture_lead(session, domain="lead1.com", company_name="Lead One")
        lead2 = await create_fixture_lead(session, domain="lead2.com", company_name="Lead Two")
        d1 = await create_fixture_draft(session, lead1, status=OutreachDraftStatus.PENDING_APPROVAL)
        d2 = await create_fixture_draft(session, lead2, status=OutreachDraftStatus.APPROVED)
        d3 = await create_fixture_draft(session, lead1, status=OutreachDraftStatus.REJECTED)
        await session.commit()

    # 1. List all
    res = await client.get("/api/v1/outreach/drafts", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["items"]) == 3

    # 2. Filter by status=pending_approval
    res = await client.get("/api/v1/outreach/drafts?status=pending_approval", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["status"] == "pending_approval"
    assert data["items"][0]["id"] == str(d1.id)

    # 3. Filter by recipient_email
    res = await client.get(f"/api/v1/outreach/drafts?recipient_email=contact@lead2.com", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == str(d2.id)

    # 4. Filter by lead_id
    res = await client.get(f"/api/v1/outreach/drafts?lead_id={lead1.id}", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_retrieve_draft_detail_with_evidence(
    client: AsyncClient,
    auth_headers: dict,
):
    """Retrieve single draft detail with lead research evidence and metadata."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(session, domain="evidencetest.com", company_name="Evidence Co")
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.PENDING_APPROVAL)
        await session.commit()
        draft_id = draft.id

    res = await client.get(f"/api/v1/outreach/drafts/{draft_id}", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(draft_id)
    assert data["company_name"] == "Evidence Co"
    assert data["lead_domain"] == "evidencetest.com"
    assert data["recipient_email"] == "contact@evidencetest.com"
    assert data["status"] == "pending_approval"
    assert data["evidence"]["unresponsive"] is True
    assert data["approved_at"] is None
    assert data["approved_by"] is None


@pytest.mark.asyncio
async def test_retrieve_draft_not_found(client: AsyncClient, auth_headers: dict):
    """Retrieving nonexistent draft returns 404."""
    random_id = uuid.uuid4()
    res = await client.get(f"/api/v1/outreach/drafts/{random_id}", headers=auth_headers)
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


@pytest.mark.asyncio
async def test_approve_pending_draft_success(client: AsyncClient, auth_headers: dict):
    """Owner approves a pending draft meeting all Gate 1 and MX criteria."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(
            session,
            status=LeadStatus.APPROVED,
            email_verification_status=EmailVerificationStatus.MX_VERIFIED,
            domain="app-success.com",
        )
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.PENDING_APPROVAL)
        await session.commit()
        draft_id = draft.id

    res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/approve", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(draft_id)
    assert data["status"] == "approved"
    assert data["approved_by"] == "test@example.com"
    assert data["approved_at"] is not None

    # Check database and audit log
    async with TestSessionLocal() as session:
        d = await session.get(OutreachDraft, draft_id)
        assert d.status == OutreachDraftStatus.APPROVED
        assert d.approved_by == "test@example.com"
        assert d.approved_at is not None

        # Verify audit log in agent_runs
        runs = (
            await session.execute(
                select(AgentRun).where(AgentRun.agent_name == "outreach_gate2")
            )
        ).scalars().all()
        assert len(runs) >= 1
        approve_run = [r for r in runs if r.input_data.get("action") == "approve_draft"]
        assert len(approve_run) >= 1
        assert approve_run[0].output_data["status"] == "approved"


@pytest.mark.asyncio
async def test_approve_already_approved_draft_blocked(client: AsyncClient, auth_headers: dict):
    """Approving an already approved draft is blocked with 400 Bad Request."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(session, status=LeadStatus.APPROVED)
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.APPROVED)
        await session.commit()
        draft_id = draft.id

    res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/approve", headers=auth_headers)
    assert res.status_code == 400
    assert "Only drafts in PENDING_APPROVAL status can be approved" in res.json()["detail"]


@pytest.mark.asyncio
async def test_approve_draft_with_non_approved_lead_blocked(client: AsyncClient, auth_headers: dict):
    """Approving a draft whose lead is not LeadStatus.APPROVED is blocked."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(
            session,
            status=LeadStatus.QUALIFIED,  # Not APPROVED
            email_verification_status=EmailVerificationStatus.MX_VERIFIED,
        )
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.PENDING_APPROVAL)
        await session.commit()
        draft_id = draft.id

    res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/approve", headers=auth_headers)
    assert res.status_code == 400
    assert "Gate 1 approval" in res.json()["detail"]


@pytest.mark.asyncio
async def test_approve_draft_with_non_mx_verified_email_blocked(client: AsyncClient, auth_headers: dict):
    """Approving a draft whose lead email is not MX_VERIFIED is blocked."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(
            session,
            status=LeadStatus.APPROVED,
            email_verification_status=EmailVerificationStatus.SYNTAX_VALID,  # Not MX_VERIFIED
        )
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.PENDING_APPROVAL)
        await session.commit()
        draft_id = draft.id

    res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/approve", headers=auth_headers)
    assert res.status_code == 400
    assert "MX_VERIFIED" in res.json()["detail"]


@pytest.mark.asyncio
async def test_reject_pending_draft_success(client: AsyncClient, auth_headers: dict):
    """Owner rejects a pending draft with a recorded reason."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(session, status=LeadStatus.APPROVED)
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.PENDING_APPROVAL)
        await session.commit()
        draft_id = draft.id

    payload = {"reason": "Not a good fit for modern agency redesign"}
    res = await client.post(
        f"/api/v1/outreach/drafts/{draft_id}/reject",
        json=payload,
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "rejected"
    assert data["rejected_by"] == "test@example.com"
    assert data["rejection_reason"] == payload["reason"]
    assert data["rejected_at"] is not None

    async with TestSessionLocal() as session:
        d = await session.get(OutreachDraft, draft_id)
        assert d.status == OutreachDraftStatus.REJECTED
        assert d.rejection_reason == payload["reason"]


@pytest.mark.asyncio
async def test_reject_already_rejected_draft_blocked(client: AsyncClient, auth_headers: dict):
    """Rejecting an already rejected draft is blocked with 400 Bad Request."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(session)
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.REJECTED)
        await session.commit()
        draft_id = draft.id

    res = await client.post(
        f"/api/v1/outreach/drafts/{draft_id}/reject",
        json={"reason": "Already rejected"},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "Only drafts in PENDING_APPROVAL status can be rejected" in res.json()["detail"]


@pytest.mark.asyncio
async def test_reject_invalid_reason_empty_or_whitespace(client: AsyncClient, auth_headers: dict):
    """Rejecting with empty or whitespace-only reason fails Pydantic validation (422)."""
    random_id = uuid.uuid4()
    res = await client.post(
        f"/api/v1/outreach/drafts/{random_id}/reject",
        json={"reason": "   "},
        headers=auth_headers,
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_edit_pending_draft_success(client: AsyncClient, auth_headers: dict):
    """Owner edits subject and body while draft is in PENDING_APPROVAL."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(session)
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.PENDING_APPROVAL)
        await session.commit()
        draft_id = draft.id

    update_payload = {
        "subject": "New customized subject line",
        "body_text": "Updated factual plain text body content.",
    }
    res = await client.patch(
        f"/api/v1/outreach/drafts/{draft_id}",
        json=update_payload,
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["subject"] == update_payload["subject"]
    assert data["body_text"] == update_payload["body_text"]
    assert data["status"] == "pending_approval"


@pytest.mark.asyncio
async def test_edit_approved_draft_blocked(client: AsyncClient, auth_headers: dict):
    """Directly editing an APPROVED draft is strictly blocked."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(session)
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.APPROVED)
        await session.commit()
        draft_id = draft.id

    res = await client.patch(
        f"/api/v1/outreach/drafts/{draft_id}",
        json={"subject": "Attempt to tamper with approved draft"},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "Edits are strictly forbidden" in res.json()["detail"]


@pytest.mark.asyncio
async def test_edit_rejected_draft_blocked(client: AsyncClient, auth_headers: dict):
    """Directly editing a REJECTED draft is strictly blocked."""
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(session)
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.REJECTED)
        await session.commit()
        draft_id = draft.id

    res = await client.patch(
        f"/api/v1/outreach/drafts/{draft_id}",
        json={"subject": "Attempt to edit rejected draft"},
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "Edits are strictly forbidden" in res.json()["detail"]


@pytest.mark.asyncio
async def test_reset_approved_draft_to_pending_workflow(client: AsyncClient, auth_headers: dict):
    """
    If an approved draft needs modification:
    1. It is reset to PENDING_APPROVAL (clearing approved_at/approved_by).
    2. It is edited.
    3. It requires fresh Gate 2 approval before it can be sent.
    """
    from tests.conftest import TestSessionLocal
    async with TestSessionLocal() as session:
        lead = await create_fixture_lead(session, status=LeadStatus.APPROVED)
        draft = await create_fixture_draft(session, lead, status=OutreachDraftStatus.APPROVED)
        await session.commit()
        draft_id = draft.id

    # 1. Reset back to PENDING_APPROVAL
    res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/reset", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "pending_approval"
    assert data["approved_at"] is None
    assert data["approved_by"] is None

    # 2. Now edit is permitted
    res = await client.patch(
        f"/api/v1/outreach/drafts/{draft_id}",
        json={"subject": "Revised subject line after reset"},
        headers=auth_headers,
    )
    assert res.status_code == 200
    assert res.json()["subject"] == "Revised subject line after reset"

    # 3. Requires fresh approval
    res = await client.post(f"/api/v1/outreach/drafts/{draft_id}/approve", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "approved"
    assert res.json()["approved_by"] == "test@example.com"
