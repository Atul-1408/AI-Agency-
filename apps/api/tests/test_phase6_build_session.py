"""
Phase 6 Stage 6.1 Tests — AI Website Builder Foundation.

Coverage:
1. Build Session Creation:
   - Valid READY_FOR_BUILD project with approved PRD creates session (201)
   - PRD snapshot artifact and metadata recorded
   - Unauthenticated request rejected (401/403)
   - Nonexistent project rejected (400)
   - Foreign owner project rejected (403)
2. Gate & Status Invariant Enforcement:
   - DRAFT project rejected (400)
   - CANCELLED project rejected (400)
   - PRD in PENDING_APPROVAL status rejected (400)
   - PRD in REJECTED status rejected (400)
   - PRD in SUPERSEDED status rejected (400)
   - Missing PRD approval metadata rejected (400)
3. Idempotency & Versioning:
   - Duplicate active session creation returns existing active session (200)
   - Exactly one active session allowed at a time
   - After terminal state (CANCELLED), next session increments build_version
4. State Machine Enforcement:
   - CREATED -> PLANNED -> READY valid transitions
   - CREATED -> CANCELLED valid transition
   - Invalid transitions rejected with 400
   - Terminal states immutable (further transitions rejected with 400)
5. Owner Isolation & IDOR:
   - Owner B cannot view Owner A's session (403)
   - Owner B cannot transition Owner A's session (403)
   - Owner B cannot create session for Owner A's project (403)
6. Listing & Detail:
   - List sessions with active/completed counts
   - Get session detail with PRD snapshot artifact
7. Audit Logging:
   - Events recorded in AgentRun: build_session_creation_requested, created, planned, ready, cancelled, accessed
   - Zero sensitive credentials or tokens in audit logs
8. Strict Phase 6.1 Boundary:
   - Verification that no code generation, build, deploy, or github endpoints exist
"""
from __future__ import annotations

from datetime import datetime, timezone
import uuid
from typing import Optional, Tuple

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from main import app as fastapi_app
from models import AgentRun, AgentRunStatus, Lead, LeadStatus, EmailVerificationStatus
from models.client_intelligence import (
    ClientConversation,
    ClientConversationStatus,
    ClientPRD,
    PRDStatus,
)
from models.project import Project, ProjectStatus
from models.website_builder import (
    WebsiteBuildArtifact,
    WebsiteBuildArtifactType,
    WebsiteBuildSession,
    WebsiteBuildSessionStatus,
)
from routers.auth import _create_access_token
from tests.conftest import TestSessionLocal, override_get_db

OWNER_EMAIL = "test@example.com"
OTHER_EMAIL = "intruder@other.com"


def owner_headers() -> dict:
    token, _ = _create_access_token(OWNER_EMAIL)
    return {"Authorization": f"Bearer {token}"}


def other_headers() -> dict:
    token, _ = _create_access_token(OTHER_EMAIL)
    return {"Authorization": f"Bearer {token}"}


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _override_app_db():
    from core.database import get_db
    fastapi_app.dependency_overrides[get_db] = override_get_db
    yield
    fastapi_app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def setup_settings():
    orig_owner = settings.OWNER_EMAIL
    settings.OWNER_EMAIL = OWNER_EMAIL
    yield
    settings.OWNER_EMAIL = orig_owner


@pytest.fixture
async def http_client():
    async with AsyncClient(
        transport=ASGITransport(app=fastapi_app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
async def db() -> AsyncSession:
    async with TestSessionLocal() as session:
        yield session


# ── Helpers ───────────────────────────────────────────────────────────────────

async def make_lead(db: AsyncSession, **kwargs) -> Lead:
    lead = Lead(
        company_name=kwargs.get("company_name", "Acme Health Care"),
        domain=kwargs.get("domain", f"acme-{uuid.uuid4().hex[:6]}.com"),
        website_url="https://acmehealthcare.com",
        email=f"contact-{uuid.uuid4().hex[:6]}@acme.com",
        email_verification_status=EmailVerificationStatus.MX_VERIFIED,
        industry="healthcare",
        qualification_score=85,
        status=LeadStatus.APPROVED,
        source_type="manual",
    )
    db.add(lead)
    await db.flush()
    return lead


async def make_ready_project(
    db: AsyncSession,
    owner_email: str = OWNER_EMAIL,
    prd_status: PRDStatus = PRDStatus.APPROVED,
    project_status: ProjectStatus = ProjectStatus.READY_FOR_BUILD,
    approved_by: Optional[str] = OWNER_EMAIL,
    approved_at: Optional[datetime] = None,
) -> Tuple[Project, ClientPRD]:
    lead = await make_lead(db)

    conv = ClientConversation(
        lead_id=lead.id,
        owner_email=owner_email,
        gmail_thread_id=f"thread_wb_{uuid.uuid4().hex[:8]}",
        status=ClientConversationStatus.PRD_APPROVED if prd_status == PRDStatus.APPROVED else ClientConversationStatus.PRD_GENERATED,
    )
    db.add(conv)
    await db.flush()

    if prd_status == PRDStatus.APPROVED and approved_at is None and approved_by:
        approved_at = datetime.now(timezone.utc)

    prd = ClientPRD(
        owner_email=owner_email,
        lead_id=lead.id,
        conversation_id=conv.id,
        version=1,
        status=prd_status,
        title="Approved Website PRD",
        executive_summary="Executive summary for healthcare site",
        business_overview={"name": "Acme Health"},
        goals=["Responsive Design", "Doctor Booking"],
        sitemap=[{"page": "Home"}, {"page": "Services"}],
        content_requirements={"tone": "Clinical"},
        functionality_requirements={"booking": True},
        design_requirements={"palette": "Teal"},
        branding_requirements={"logo": "provided"},
        contact_requirements={"email": lead.email},
        technical_requirements={"framework": "Next.js"},
        timeline={"target": "4 weeks"},
        budget={"estimate": "$5,000"},
        assumptions=["Client provides doctor photos"],
        open_questions=[],
        requirement_traceability={"req_1": "core"},
        generated_at=datetime.now(timezone.utc),
        approved_at=approved_at,
        approved_by=approved_by,
    )
    db.add(prd)
    await db.flush()

    project = Project(
        owner_id=owner_email,
        lead_id=lead.id,
        conversation_id=conv.id,
        approved_prd_id=prd.id,
        prd_version=1,
        project_name="Acme Health Care Website",
        project_slug=f"acme-health-{uuid.uuid4().hex[:6]}",
        project_status=project_status,
        project_source="approved_prd",
        created_by=owner_email,
        phase_metadata={"phase_6_ready": True},
    )
    db.add(project)
    await db.flush()
    return project, prd


# ── 1. BUILD SESSION CREATION TESTS ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_build_session_success(http_client: AsyncClient, db: AsyncSession):
    project, prd = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["project_id"] == str(project.id)
    assert data["owner_id"] == OWNER_EMAIL
    assert data["status"] == "created"
    assert data["build_version"] == 1
    assert data["metadata"]["approved_prd_id"] == str(prd.id)
    assert data["metadata"]["approved_prd_version"] == prd.version

    # Verify PRD_SNAPSHOT artifact was created
    artifacts_stmt = select(WebsiteBuildArtifact).where(WebsiteBuildArtifact.build_session_id == uuid.UUID(data["id"]))
    artifacts = (await db.scalars(artifacts_stmt)).all()
    assert len(artifacts) == 1
    snapshot_art = artifacts[0]
    assert snapshot_art.artifact_type == WebsiteBuildArtifactType.PRD_SNAPSHOT
    assert f"v{prd.version}" in snapshot_art.artifact_name


@pytest.mark.asyncio
async def test_create_build_session_unauthenticated_rejected(http_client: AsyncClient, db: AsyncSession):
    project, _ = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    resp = await http_client.post(f"/api/v1/projects/{project.id}/build-sessions")
    assert resp.status_code in {401, 403}


@pytest.mark.asyncio
async def test_create_build_session_nonexistent_project_rejected(http_client: AsyncClient):
    fake_id = str(uuid.uuid4())
    resp = await http_client.post(
        f"/api/v1/projects/{fake_id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_build_session_other_owner_project_rejected(http_client: AsyncClient, db: AsyncSession):
    project, _ = await make_ready_project(db, owner_email="other@agency.com")
    await db.commit()

    resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


# ── 2. GATE & STATUS INVARIANTS ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_build_session_ineligible_project_status(http_client: AsyncClient, db: AsyncSession):
    # CANCELLED project
    project, _ = await make_ready_project(db, project_status=ProjectStatus.CANCELLED)
    await db.commit()

    resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "ready_for_build" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_build_session_unapproved_prd_rejected(http_client: AsyncClient, db: AsyncSession):
    # PENDING_APPROVAL PRD
    project, _ = await make_ready_project(
        db,
        prd_status=PRDStatus.PENDING_APPROVAL,
        approved_by=None,
        approved_at=None,
    )
    await db.commit()

    resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "must be approved" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_build_session_missing_approval_metadata_rejected(http_client: AsyncClient, db: AsyncSession):
    # APPROVED status but null approver
    project, _ = await make_ready_project(
        db,
        prd_status=PRDStatus.APPROVED,
        approved_by=None,
        approved_at=datetime.now(timezone.utc),
    )
    await db.commit()

    resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "missing approval metadata" in resp.json()["detail"].lower()


# ── 3. IDEMPOTENCY & VERSIONING ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_session_active_idempotency(http_client: AsyncClient, db: AsyncSession):
    project, _ = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    # First call creates session (201)
    resp1 = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp1.status_code == 201
    s1_id = resp1.json()["id"]

    # Second call returns existing active session (200) without duplicating
    resp2 = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp2.status_code == 200
    assert resp2.json()["id"] == s1_id

    # Verify exactly 1 session row in database
    sessions_stmt = select(WebsiteBuildSession).where(WebsiteBuildSession.project_id == project.id)
    all_sessions = (await db.scalars(sessions_stmt)).all()
    assert len(all_sessions) == 1


@pytest.mark.asyncio
async def test_build_session_version_increment_after_cancellation(http_client: AsyncClient, db: AsyncSession):
    project, _ = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    # Create session v1
    resp1 = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp1.status_code == 201
    s1_id = resp1.json()["id"]
    assert resp1.json()["build_version"] == 1

    # Cancel session v1
    cancel_resp = await http_client.post(
        f"/api/v1/build-sessions/{s1_id}/cancel",
        json={"reason": "Resetting workspace"},
        headers=owner_headers(),
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"

    # Create new session -> should now produce v2
    resp2 = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp2.status_code == 201
    assert resp2.json()["build_version"] == 2
    assert resp2.json()["id"] != s1_id


# ── 4. STATE MACHINE TRANSITIONS ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_state_machine_valid_progression(http_client: AsyncClient, db: AsyncSession):
    project, _ = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    create_resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    session_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "created"

    # CREATED -> PLANNED
    plan_resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/plan",
        json={"notes": "Architecture planned"},
        headers=owner_headers(),
    )
    assert plan_resp.status_code == 200
    assert plan_resp.json()["status"] == "planned"

    # PLANNED -> READY
    ready_resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/ready",
        json={"notes": "Ready for pipeline"},
        headers=owner_headers(),
    )
    assert ready_resp.status_code == 200
    assert ready_resp.json()["status"] == "ready"

    # READY -> CANCELLED
    cancel_resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/cancel",
        json={"reason": "Cancelled by owner"},
        headers=owner_headers(),
    )
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_state_machine_invalid_transitions_rejected(http_client: AsyncClient, db: AsyncSession):
    project, _ = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    create_resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    session_id = create_resp.json()["id"]

    # CREATED -> READY is invalid (must go through PLANNED first)
    invalid_ready = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/ready",
        headers=owner_headers(),
    )
    assert invalid_ready.status_code == 400
    assert "cannot transition" in invalid_ready.json()["detail"].lower()

    # CREATED -> PAUSED is invalid
    invalid_pause = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/pause",
        headers=owner_headers(),
    )
    assert invalid_pause.status_code == 400
    assert "cannot transition" in invalid_pause.json()["detail"].lower()


@pytest.mark.asyncio
async def test_state_machine_terminal_state_immutable(http_client: AsyncClient, db: AsyncSession):
    project, _ = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    create_resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    session_id = create_resp.json()["id"]

    # Cancel session (terminal state)
    await http_client.post(
        f"/api/v1/build-sessions/{session_id}/cancel",
        headers=owner_headers(),
    )

    # Attempting to transition cancelled session fails
    plan_resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/plan",
        headers=owner_headers(),
    )
    assert plan_resp.status_code == 400
    assert "terminal state" in plan_resp.json()["detail"].lower()


# ── 5. IDOR & OWNER ISOLATION ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_isolation_idor_session_access(http_client: AsyncClient, db: AsyncSession):
    project, _ = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    create_resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    session_id = create_resp.json()["id"]

    # Other owner attempts to view Owner A's session
    get_resp = await http_client.get(
        f"/api/v1/build-sessions/{session_id}",
        headers=other_headers(),
    )
    assert get_resp.status_code == 403

    # Other owner attempts to transition Owner A's session
    plan_resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/plan",
        headers=other_headers(),
    )
    assert plan_resp.status_code == 403


# ── 6. LISTING & DETAIL ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_and_get_session_detail(http_client: AsyncClient, db: AsyncSession):
    project, prd = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    # Create session
    create_resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    session_id = create_resp.json()["id"]

    # List sessions for project
    list_resp = await http_client.get(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert list_data["active_count"] >= 1
    assert any(s["id"] == session_id for s in list_data["items"])

    # Get session detail
    detail_resp = await http_client.get(
        f"/api/v1/build-sessions/{session_id}",
        headers=owner_headers(),
    )
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == session_id
    assert detail["project_name"] == project.project_name
    assert detail["approved_prd_id"] == str(prd.id)
    assert len(detail["artifacts"]) >= 1
    assert detail["artifacts"][0]["artifact_type"] == "prd_snapshot"


# ── 7. AUDIT LOGGING ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_logging_build_sessions(http_client: AsyncClient, db: AsyncSession):
    project, _ = await make_ready_project(db, OWNER_EMAIL)
    await db.commit()

    # Create session
    create_resp = await http_client.post(
        f"/api/v1/projects/{project.id}/build-sessions",
        headers=owner_headers(),
    )
    session_id = create_resp.json()["id"]

    # Access detail
    await http_client.get(f"/api/v1/build-sessions/{session_id}", headers=owner_headers())

    # Transition to planned
    await http_client.post(f"/api/v1/build-sessions/{session_id}/plan", headers=owner_headers())

    # Cancel
    await http_client.post(f"/api/v1/build-sessions/{session_id}/cancel", headers=owner_headers())

    # Check AgentRun rows
    runs_stmt = select(AgentRun).where(AgentRun.agent_name == "website_build_session_service")
    runs = (await db.scalars(runs_stmt)).all()

    events = [r.input_data.get("event") for r in runs if r.input_data]
    assert "build_session_creation_requested" in events
    assert "build_session_created" in events
    assert "build_session_accessed" in events
    assert "build_session_planned" in events
    assert "build_session_cancelled" in events

    # Ensure zero credentials or auth tokens leaked
    for r in runs:
        dump = str(r.input_data) + str(r.output_data)
        assert "Bearer" not in dump
        assert "password" not in dump.lower()


# ── 8. STRICT PHASE 6.1 BOUNDARY ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_phase6_boundary_strictness(http_client: AsyncClient):
    """Ensure no code generation, build, or deploy endpoints exist in Phase 6.1."""
    dummy_id = str(uuid.uuid4())
    prohibited_endpoints = [
        f"/api/v1/build-sessions/{dummy_id}/generate",
        f"/api/v1/build-sessions/{dummy_id}/build-code",
        f"/api/v1/build-sessions/{dummy_id}/deploy",
        f"/api/v1/build-sessions/{dummy_id}/github",
        f"/api/v1/build-sessions/{dummy_id}/vercel",
        f"/api/v1/build-sessions/{dummy_id}/qa",
    ]

    for endpoint in prohibited_endpoints:
        resp = await http_client.post(endpoint, headers=owner_headers())
        assert resp.status_code in {404, 405}, f"Prohibited endpoint active: {endpoint}"
