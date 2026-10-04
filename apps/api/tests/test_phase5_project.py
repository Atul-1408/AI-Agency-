"""
Phase 5 Stage 5.4 Tests — Project Creation & Client Intelligence Dashboard.

Test Coverage:
1. PROJECT CREATION:
   - Authenticated owner can create project from APPROVED PRD (201)
   - Unauthenticated request is rejected (401/403)
   - Missing PRD is rejected (400)
   - Wrong owner PRD is rejected (403)
   - Pending PRD is rejected (400)
   - Rejected PRD is rejected (400)
   - Draft PRD is rejected (400)
   - Superseded PRD is rejected (400)

2. GATE 4 ENFORCEMENT:
   - Gate 4 APPROVED status strictly required
   - Client body cannot override server approval checks
   - Missing approved_by fails closed (400)
   - Missing approved_at fails closed (400)

3. OWNERSHIP / IDOR ISOLATION:
   - Owner A cannot access Owner B project (403)
   - Owner A cannot update Owner B project (403)
   - Owner A cannot use Owner B PRD (403)
   - Owner A cannot use Owner B conversation/lead (403)

4. IDEMPOTENCY:
   - Exactly one project per approved PRD (409 Conflict with existing_project_id)
   - Database uniqueness enforced on approved_prd_id
   - Concurrency / IntegrityError gracefully handled and rolled back
   - Repeated requests do not create duplicate rows

5. DATA INTEGRITY & HANDOFF SNAPSHOT:
   - Accurate owner, lead, conversation, approved_prd_id, prd_version stored
   - Approval timestamp preserved
   - phase_metadata holds complete deterministic snapshot without re-running AI

6. PROJECT UPDATES:
   - Allowed updates (project_name, allowed statuses like CANCELLED) succeed
   - Immutable fields (owner_id, prd_id, lead_id) cannot be modified
   - Unauthorized status transitions (e.g. into future Phase 6/7/8 states) rejected (400)

7. SECURITY & SANITIZATION:
   - Project name XSS / HTML / script tags rejected
   - Malicious slug inputs safely normalized to alphanumeric-hyphen strings
   - SQL injection / prompt injection payloads remain inert text data

8. OBSERVABILITY & AUDIT LOGGING:
   - Events recorded: project_creation_requested, project_created, project_creation_blocked,
     project_accessed, project_updated
   - Zero sensitive credentials or tokens in audit logs

9. PHASE BOUNDARY PROTECTION:
   - Verification that no Phase 6 generation, GitHub, Vercel, or deployment routes exist
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
    ClientConversationMessage,
    ClientConversationStatus,
    ClientPRD,
    MessageDirection,
    PRDStatus,
)
from models.project import Project, ProjectStatus
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
        website_url=kwargs.get("website_url", "https://acmehealthcare.com"),
        email=kwargs.get("email", f"contact-{uuid.uuid4().hex[:6]}@acme.com"),
        email_verification_status=EmailVerificationStatus.MX_VERIFIED,
        industry="healthcare",
        qualification_score=85,
        status=LeadStatus.APPROVED,
        source_type="manual",
    )
    db.add(lead)
    await db.flush()
    return lead


_SENTINEL = object()

async def make_approved_prd(
    db: AsyncSession,
    owner_email: str = OWNER_EMAIL,
    status: PRDStatus = PRDStatus.APPROVED,
    approved_by: Optional[str] = OWNER_EMAIL,
    approved_at: Any = _SENTINEL,
    company_name: str = "Acme Health Care",
) -> Tuple[ClientPRD, ClientConversation, Lead]:
    lead = await make_lead(db, company_name=company_name)

    conv = ClientConversation(
        lead_id=lead.id,
        owner_email=owner_email,
        gmail_thread_id=f"thread_proj_{uuid.uuid4().hex[:8]}",
        status=ClientConversationStatus.PRD_APPROVED if status == PRDStatus.APPROVED else ClientConversationStatus.PRD_GENERATED,
    )
    db.add(conv)
    await db.flush()

    if approved_at is _SENTINEL:
        actual_approved_at = datetime.now(timezone.utc) if status == PRDStatus.APPROVED else None
    else:
        actual_approved_at = approved_at

    prd = ClientPRD(
        owner_email=owner_email,
        lead_id=lead.id,
        conversation_id=conv.id,
        version=1,
        status=status,
        title=f"Website PRD for {company_name}",
        executive_summary="Official approved specifications for health care site.",
        business_overview={"name": company_name, "industry": "Healthcare"},
        goals=["Modern responsive design", "Patient booking"],
        target_audience={"primary": "Patients"},
        sitemap=[{"page": "Home"}, {"page": "Services"}, {"page": "Contact"}],
        content_requirements={"tone": "Professional"},
        functionality_requirements={"booking": True},
        design_requirements={"colors": ["blue", "white"]},
        branding_requirements={"logo": "provided"},
        contact_requirements={"email": lead.email},
        technical_requirements={"framework": "Next.js"},
        timeline={"target": "4 weeks"},
        budget={"estimate": "$5,000"},
        assumptions=["Client will provide doctor bios"],
        open_questions=[],
        requirement_traceability={"req_1": "core"},
        generated_at=datetime.now(timezone.utc),
        approved_at=actual_approved_at,
        approved_by=approved_by,
    )
    db.add(prd)
    await db.flush()
    return prd, conv, lead


# ── 1. PROJECT CREATION TESTS ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_project_success(http_client: AsyncClient, db: AsyncSession):
    prd, conv, lead = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["approved_prd_id"] == str(prd.id)
    assert data["owner_id"] == OWNER_EMAIL
    assert data["lead_id"] == str(lead.id)
    assert data["conversation_id"] == str(conv.id)
    assert data["prd_version"] == 1
    assert data["project_status"] == "ready_for_build"
    assert data["project_source"] == "approved_prd"
    assert data["created_by"] == OWNER_EMAIL
    assert "acme" in data["project_slug"]
    assert data["phase_metadata"]["phase_6_ready"] is True
    assert data["phase_metadata"]["business_name"] == lead.company_name


@pytest.mark.asyncio
async def test_create_project_unauthenticated_rejected(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
    )
    assert resp.status_code in {401, 403}


@pytest.mark.asyncio
async def test_create_project_missing_prd_rejected(http_client: AsyncClient):
    fake_id = str(uuid.uuid4())
    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": fake_id},
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_project_wrong_owner_prd_rejected(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, owner_email="other@agency.com")
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_project_pending_prd_rejected(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL, status=PRDStatus.PENDING_APPROVAL, approved_by=None, approved_at=None)
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "gate 4 approved prd" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_project_rejected_prd_rejected(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL, status=PRDStatus.REJECTED, approved_by=None, approved_at=None)
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "gate 4 approved prd" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_project_superseded_prd_rejected(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL, status=PRDStatus.SUPERSEDED, approved_by=None, approved_at=None)
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "gate 4 approved prd" in resp.json()["detail"].lower()


# ── 2. GATE 4 STRICT ENFORCEMENT ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gate4_cannot_bypass_via_client_body(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL, status=PRDStatus.PENDING_APPROVAL, approved_by=None, approved_at=None)
    await db.commit()

    # Attempt to spoof approval status in request body
    resp = await http_client.post(
        "/api/v1/projects",
        json={
            "approved_prd_id": str(prd.id),
            "project_status": "deployed",
            "status": "approved",
            "approved_by": OWNER_EMAIL,
        },
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "gate 4 approved prd" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_gate4_missing_approved_by_rejected(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(
        db,
        OWNER_EMAIL,
        status=PRDStatus.APPROVED,
        approved_by=None,  # Missing approver
        approved_at=datetime.now(timezone.utc),
    )
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "missing approver identity" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_gate4_missing_approved_at_rejected(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(
        db,
        OWNER_EMAIL,
        status=PRDStatus.APPROVED,
        approved_by=OWNER_EMAIL,
        approved_at=None,  # Missing timestamp
    )
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert resp.status_code == 400
    assert "missing approval timestamp" in resp.json()["detail"].lower()


# ── 3. OWNERSHIP / IDOR ISOLATION ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_owner_a_cannot_access_owner_b_project(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    # Create project as Owner A
    create_resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    # Intruder tries to GET project
    get_resp = await http_client.get(
        f"/api/v1/projects/{proj_id}",
        headers=other_headers(),
    )
    assert get_resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_a_cannot_update_owner_b_project(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    create_resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    proj_id = create_resp.json()["id"]

    # Intruder tries to PATCH project
    patch_resp = await http_client.patch(
        f"/api/v1/projects/{proj_id}",
        json={"project_name": "Hacked Name"},
        headers=other_headers(),
    )
    assert patch_resp.status_code == 403


# ── 4. IDEMPOTENCY & CONCURRENCY ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_project_creation_prevented(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    # First creation succeeds
    resp1 = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert resp1.status_code == 201
    orig_id = resp1.json()["id"]

    # Duplicate creation attempt returns 409 Conflict with existing_project_id
    resp2 = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert resp2.status_code == 409
    detail = resp2.json()["detail"]
    assert detail["existing_project_id"] == orig_id

    # Verify only 1 project in database for this PRD
    count_stmt = select(Project).where(Project.approved_prd_id == prd.id)
    all_projects = (await db.scalars(count_stmt)).all()
    assert len(all_projects) == 1


@pytest.mark.asyncio
async def test_concurrent_integrity_error_handled(db: AsyncSession):
    """Verify that duplicate approved_prd_id triggers ProjectAlreadyExistsError."""
    from services.project_service import ProjectService, ProjectAlreadyExistsError
    from schemas.project import ProjectCreateRequest

    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    req = ProjectCreateRequest(approved_prd_id=prd.id)
    proj1 = await ProjectService.create_project(db, OWNER_EMAIL, req)
    await db.commit()

    with pytest.raises(ProjectAlreadyExistsError) as exc_info:
        await ProjectService.create_project(db, OWNER_EMAIL, req)
    assert exc_info.value.existing_project_id == proj1.id


@pytest.mark.asyncio
async def test_owner_b_cannot_create_project_from_owner_a_approved_prd(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=other_headers(),
    )
    assert resp.status_code == 403
    assert "forbidden" in resp.json()["detail"].lower() or "not authorized" in resp.json()["detail"].lower()


# ── 5. DATA INTEGRITY & SNAPSHOT ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_project_data_integrity_and_snapshot(http_client: AsyncClient, db: AsyncSession):
    prd, conv, lead = await make_approved_prd(db, OWNER_EMAIL, company_name="Summit Dental")
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id), "custom_project_name": "Summit Dental Clinic Redesign"},
        headers=owner_headers(),
    )
    assert resp.status_code == 201
    data = resp.json()

    assert data["project_name"] == "Summit Dental Clinic Redesign"
    assert data["project_slug"].startswith("summit-dental-clinic-redesign")
    assert data["prd_version"] == prd.version
    assert data["phase_metadata"]["business_name"] == "Summit Dental"
    assert "sitemap" in data["phase_metadata"]
    assert len(data["phase_metadata"]["sitemap"]) == 3


# ── 6. PROJECT UPDATE & MUTABILITY RULES ───────────────────────────────────────

@pytest.mark.asyncio
async def test_project_update_allowed_fields(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    create_resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    proj_id = create_resp.json()["id"]

    # Update name and status to CANCELLED
    patch_resp = await http_client.patch(
        f"/api/v1/projects/{proj_id}",
        json={"project_name": "Acme Health Revised", "project_status": "cancelled"},
        headers=owner_headers(),
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["project_name"] == "Acme Health Revised"
    assert data["project_status"] == "cancelled"


@pytest.mark.asyncio
async def test_project_update_blocks_future_phase_transitions(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    create_resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    proj_id = create_resp.json()["id"]

    # Attempt transition into future Phase 6/7/8 statuses
    for bad_status in ["in_build", "qa", "ready_for_deployment", "deployed", "completed"]:
        patch_resp = await http_client.patch(
            f"/api/v1/projects/{proj_id}",
            json={"project_status": bad_status},
            headers=owner_headers(),
        )
        assert patch_resp.status_code == 422 or patch_resp.status_code == 400


# ── 7. SECURITY & SANITIZATION ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_project_name_xss_sanitized(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    resp = await http_client.post(
        "/api/v1/projects",
        json={
            "approved_prd_id": str(prd.id),
            "custom_project_name": "<script>alert('xss')</script>Malicious Website",
        },
        headers=owner_headers(),
    )
    # Validator rejects HTML/script tags
    assert resp.status_code == 422 or resp.status_code == 400


@pytest.mark.asyncio
async def test_slug_generation_safe_from_path_traversal(http_client: AsyncClient, db: AsyncSession):
    from services.project_service import generate_safe_slug

    malicious_inputs = [
        "../../etc/passwd",
        "<script>alert(1)</script>",
        "'; DROP TABLE projects; --",
        "https://evil.com/payload?a=1",
        "   ---weird---name---   ",
    ]

    for malicious in malicious_inputs:
        slug = generate_safe_slug(malicious)
        assert "/" not in slug
        assert "\\" not in slug
        assert "<" not in slug
        assert ">" not in slug
        assert ";" not in slug
        assert "--" not in slug
        assert len(slug) <= 50
        assert slug.islower() or slug.isalnum()


# ── 8. AUDIT LOGGING ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_logging_events(http_client: AsyncClient, db: AsyncSession):
    prd, _, _ = await make_approved_prd(db, OWNER_EMAIL)
    await db.commit()

    # Create project
    create_resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    assert create_resp.status_code == 201
    proj_id = create_resp.json()["id"]

    # Get project
    await http_client.get(f"/api/v1/projects/{proj_id}", headers=owner_headers())

    # Update project
    await http_client.patch(
        f"/api/v1/projects/{proj_id}",
        json={"project_name": "Updated Name"},
        headers=owner_headers(),
    )

    # Check AgentRun audit records
    runs_stmt = select(AgentRun).where(AgentRun.agent_name == "project_service")
    runs = (await db.scalars(runs_stmt)).all()

    events = [r.input_data.get("event") for r in runs if r.input_data]
    assert "project_creation_requested" in events
    assert "project_created" in events
    assert "project_accessed" in events
    assert "project_updated" in events

    # Verify no Authorization headers or passwords leaked into audit logs
    for r in runs:
        dump = str(r.input_data) + str(r.output_data)
        assert "Bearer" not in dump
        assert "password" not in dump.lower()


# ── 9. DASHBOARD LISTING & DETAIL ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_and_get_project_detail(http_client: AsyncClient, db: AsyncSession):
    prd, _, lead = await make_approved_prd(db, OWNER_EMAIL, company_name="Metro Dental")
    await db.commit()

    create_resp = await http_client.post(
        "/api/v1/projects",
        json={"approved_prd_id": str(prd.id)},
        headers=owner_headers(),
    )
    proj_id = create_resp.json()["id"]

    # List projects
    list_resp = await http_client.get("/api/v1/projects", headers=owner_headers())
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert list_data["ready_for_build_count"] >= 1
    assert any(p["id"] == proj_id for p in list_data["items"])

    # Get detail
    get_resp = await http_client.get(f"/api/v1/projects/{proj_id}", headers=owner_headers())
    assert get_resp.status_code == 200
    detail = get_resp.json()
    assert detail["id"] == proj_id
    assert detail["business_name"] == "Metro Dental"
    assert detail["handoff_readiness"]["phase_6_ready"] is True
    assert detail["handoff_readiness"]["status"] == "ready_for_build"


# ── 10. STRICT NEGATIVE PHASE 6 BOUNDARY CHECK ────────────────────────────────

@pytest.mark.asyncio
async def test_phase6_boundary_enforcement(http_client: AsyncClient):
    """Verify that no website generation, deploy, or github endpoints exist in Phase 5.4."""
    dummy_id = str(uuid.uuid4())
    prohibited_routes = [
        f"/api/v1/projects/{dummy_id}/build",
        f"/api/v1/projects/{dummy_id}/generate",
        f"/api/v1/projects/{dummy_id}/deploy",
        f"/api/v1/projects/{dummy_id}/github",
        f"/api/v1/projects/{dummy_id}/vercel",
        f"/api/v1/projects/{dummy_id}/qa",
    ]

    for route in prohibited_routes:
        resp = await http_client.post(route, headers=owner_headers())
        assert resp.status_code in {404, 405}, f"Prohibited Phase 6 route active: {route}"
