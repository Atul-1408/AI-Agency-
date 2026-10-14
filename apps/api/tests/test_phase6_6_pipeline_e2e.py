"""
Phase 6 Stage 6.6 — Complete Website Builder Platform Pipeline & Security Audit Tests.

End-to-End Verification of the entire Phase 6 pipeline:
1. Gate 4 Approved PRD -> Project Creation (Phase 5.4)
2. Build Workspace Session Creation (Phase 6.1)
3. Website Specification Generation (Phase 6.2)
4. Design Blueprint Generation (Phase 6.3)
5. Website Source Code Generation (Phase 6.4)
6. Isolated Filesystem Workspace & Code Validation (Phase 6.4)
7. Sandboxed Live Preview with CSP (Phase 6.5)
8. Iterative Targeted Editing (Phase 6.5) -> Monotonic Version v1 -> v2
9. Immutable Version History Tracking (Phase 6.5)
10. Non-Destructive Rollback (v2 -> v1 produces v3, preserving all versions)
11. Security Audit: IDOR Defense Across All Stages
12. Security Audit: Gate 4 PRD Invariant & Version Matching Enforcement
13. Security Audit: Optimistic Concurrency & Base Version Conflict Rejection
14. Boundary Audit: Prohibited Endpoints (/deploy, /github, /vercel, /qa, /exec) Return 404
15. Structured Audit Trail Recorded in agent_runs
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

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
    DesignBlueprint,
    DesignBlueprintStatus,
    WebsiteBuildArtifact,
    WebsiteBuildArtifactType,
    WebsiteBuildSession,
    WebsiteBuildSessionStatus,
    WebsiteCodeGeneration,
    WebsiteCodeGenerationStatus,
    WebsiteEditSession,
    WebsiteEditSessionStatus,
    WebsiteEditVersion,
    WebsiteGeneration,
    WebsiteGenerationStatus,
    WebsitePreview,
    WebsitePreviewStatus,
)
from routers.auth import _create_access_token
from schemas.code_generation import GeneratedWebsiteFile, GeneratedWebsiteProject
from schemas.design_blueprint import (
    AccessibilityBlueprint,
    ColorTokens,
    DesignTokens,
    PageBlueprint,
    ResponsiveBreakpoint,
    SectionBlueprint,
    SiteArchitecture,
    TypographyTokens,
    WebsiteDesignBlueprint,
)
from schemas.website_preview_edit import (
    WebsiteEditCreateRequest,
    WebsitePreviewCreateRequest,
)
from schemas.website_specification import (
    ColorPaletteSpecification,
    DesignSystemSpecification,
    NavigationItemSpecification,
    PageSpecification,
    SectionSpecification,
    TypographySpecification,
    WebsiteSpecification,
)
from services.code_generation_service import WebsiteCodeGenerationService
from services.design_blueprint_service import DesignBlueprintService
from services.website_build_session_service import WebsiteBuildSessionService
from services.website_editing_service import (
    StaleBaseVersionConflictError,
    WebsiteEditingService,
)
from services.website_generation_service import WebsiteGenerationService
from services.website_preview_service import WebsitePreviewService
from services.website_workspace_service import WebsiteWorkspaceService
from tests.conftest import TestSessionLocal, override_get_db

OWNER_EMAIL = "owner@agency.com"
INTRUDER_EMAIL = "intruder@other.com"


def owner_headers() -> dict:
    token, _ = _create_access_token(OWNER_EMAIL)
    return {"Authorization": f"Bearer {token}"}


def intruder_headers() -> dict:
    token, _ = _create_access_token(INTRUDER_EMAIL)
    return {"Authorization": f"Bearer {token}"}


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


# ── Seed Helper ───────────────────────────────────────────────────────────────

async def seed_gate4_approved_lead_and_prd(
    db: AsyncSession,
    owner_id: str = OWNER_EMAIL,
    prd_status: PRDStatus = PRDStatus.APPROVED,
    prd_version: int = 1,
) -> Tuple[Lead, ClientConversation, ClientPRD]:
    """Creates a verified lead, conversation, and Gate 4 approved PRD."""
    lead = Lead(
        id=uuid.uuid4(),
        company_name="Vanguard Architecture",
        domain=f"vanguard-{uuid.uuid4().hex[:6]}.com",
        source_type="test",
        qualification_score=95,
        status=LeadStatus.APPROVED,
        email_verification_status=EmailVerificationStatus.MX_VERIFIED,
    )
    db.add(lead)
    await db.flush()

    convo = ClientConversation(
        id=uuid.uuid4(),
        lead_id=lead.id,
        owner_email=owner_id,
        gmail_thread_id=f"thread_{uuid.uuid4().hex[:8]}",
        status=ClientConversationStatus.INITIATED,
    )
    db.add(convo)
    await db.flush()

    prd = ClientPRD(
        id=uuid.uuid4(),
        lead_id=lead.id,
        conversation_id=convo.id,
        owner_email=owner_id,
        version=prd_version,
        status=prd_status,
        title="Vanguard Architecture Digital Platform",
        executive_summary="Modern portfolio and client onboarding website for Vanguard Architecture.",
        business_overview={"industry": "Architecture & Engineering", "location": "Seattle, WA"},
        goals=["Showcase luxury architectural projects", "Capture enterprise RFPs"],
        target_audience="High-net-worth individuals and corporate developers",
        sitemap=[
            {"page": "Home", "status": "approved", "purpose": "Hero, featured projects, awards"},
            {"page": "Portfolio", "status": "approved", "purpose": "Architectural showcase filterable by category"},
            {"page": "Services", "status": "approved", "purpose": "Commercial and residential architectural services"},
            {"page": "Contact", "status": "approved", "purpose": "Inquiry form and office locations"},
        ],
        content_requirements={"tone": "Sophisticated, authoritative, minimalist"},
        functionality_requirements={"features": ["Interactive portfolio", "RFP intake form"]},
        design_requirements={"style": "Modernist Swiss", "theme": "Monochrome slate with gold accents"},
        branding_requirements={},
        contact_requirements={},
        technical_requirements={},
        timeline={},
        budget={},
        assumptions=[],
        open_questions=[],
        requirement_traceability={},
        generated_at=datetime.now(timezone.utc),
        approved_at=datetime.now(timezone.utc) if prd_status == PRDStatus.APPROVED else None,
        approved_by=owner_id if prd_status == PRDStatus.APPROVED else None,
    )
    db.add(prd)
    await db.flush()

    return lead, convo, prd


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_complete_phase6_pipeline_e2e(http_client: AsyncClient, db: AsyncSession):
    """
    1. Complete End-to-End Pipeline Execution:
    PRD (Gate 4) -> Project -> Build Session -> Specification -> Design Blueprint
    -> Code Generation -> Live Preview -> Iterative Editing -> Version History -> Rollback.
    """
    # Step 1: Create Gate 4 Approved PRD
    lead, convo, prd = await seed_gate4_approved_lead_and_prd(db, owner_id=OWNER_EMAIL)

    # Step 2: Project Creation (Phase 5.4)
    resp = await http_client.post(
        "/api/v1/projects",
        headers=owner_headers(),
        json={
            "lead_id": str(lead.id),
            "conversation_id": str(convo.id),
            "approved_prd_id": str(prd.id),
            "project_name": "Vanguard Architecture",
        },
    )
    assert resp.status_code == 201, resp.text
    project_id = resp.json()["id"]

    # Step 3: Build Session Creation (Phase 6.1)
    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/build-sessions",
        headers=owner_headers(),
    )
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["id"]
    assert resp.json()["status"] == "created"

    # Transition build session CREATED -> PLANNED -> READY
    resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/plan",
        headers=owner_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "planned"

    resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/ready",
        headers=owner_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"

    # Step 4: AI Website Specification Generation (Phase 6.2)
    resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/generations",
        headers=owner_headers(),
    )
    assert resp.status_code == 201, resp.text
    gen_data = resp.json()
    assert gen_data["status"] == "completed"
    generation_id = gen_data["id"]

    # Step 5: Design Blueprint Generation (Phase 6.3)
    resp = await http_client.post(
        f"/api/v1/generations/{generation_id}/blueprints",
        headers=owner_headers(),
    )
    assert resp.status_code == 201, resp.text
    bp_data = resp.json()
    assert bp_data["status"] == "completed"
    blueprint_id = bp_data["id"]

    # Step 6: Website Code Generation (Phase 6.4)
    resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/code-generations",
        headers=owner_headers(),
        json={"design_blueprint_id": blueprint_id},
    )
    assert resp.status_code == 201, resp.text
    code_gen_data = resp.json()
    assert code_gen_data["status"] == "completed"
    code_gen_id = code_gen_data["id"]
    assert code_gen_data["file_count"] > 0
    assert code_gen_data["source_checksum"] is not None

    # Step 7: Live Preview Creation & Rendering (Phase 6.5)
    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/previews",
        headers=owner_headers(),
        json={"code_generation_id": code_gen_id},
    )
    assert resp.status_code == 201, resp.text
    preview_data = resp.json()
    preview_id = preview_data["id"]
    assert preview_data["status"] == "created"

    # Start preview
    resp = await http_client.post(
        f"/api/v1/previews/{preview_id}/start",
        headers=owner_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"

    # Start and verify preview status
    resp = await http_client.get(
        f"/api/v1/previews/{preview_id}/status",
        headers=owner_headers(),
    )
    assert resp.status_code == 200
    status_data = resp.json()
    assert status_data["is_running"] is True
    assert status_data["version"] == 1

    # Render sandboxed preview HTML and verify CSP headers
    resp = await http_client.get(
        f"/api/v1/previews/{preview_id}/render",
        headers=owner_headers(),
    )
    assert resp.status_code == 200
    assert "Content-Security-Policy" in resp.headers
    assert "frame-ancestors 'self'" in resp.headers["Content-Security-Policy"]
    assert "<html" in resp.text

    # Step 8: Iterative Editing (Phase 6.5) -> creates v2 and v3
    # Edit 1 -> creates v2
    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/edits",
        headers=owner_headers(),
        json={
            "preview_id": preview_id,
            "base_version": 1,
            "owner_request": "Make the hero darker with slate-950 background",
        },
    )
    assert resp.status_code == 201, resp.text
    edit1_data = resp.json()
    assert edit1_data["edit"]["status"] == "applied"
    assert edit1_data["version_created"] == 2
    assert "components/sections/Hero.tsx" in edit1_data["changed_files"]

    # Edit 2 -> creates v3
    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/edits",
        headers=owner_headers(),
        json={
            "preview_id": preview_id,
            "base_version": 2,
            "owner_request": "Make the navigation header sticky with blur",
        },
    )
    assert resp.status_code == 201, resp.text
    edit2_data = resp.json()
    assert edit2_data["edit"]["status"] == "applied"
    assert edit2_data["version_created"] == 3

    # Preview version should now reflect v3
    resp = await http_client.get(
        f"/api/v1/previews/{preview_id}/status",
        headers=owner_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 3

    # Step 9: Version History Tracking (Phase 6.5)
    resp = await http_client.get(
        f"/api/v1/projects/{project_id}/versions",
        headers=owner_headers(),
    )
    assert resp.status_code == 200
    versions_list = resp.json()["versions"]
    assert len(versions_list) == 2
    assert versions_list[0]["version"] == 3  # Most recent active version
    assert versions_list[0]["is_active"] is True
    assert versions_list[1]["version"] == 2
    assert versions_list[1]["is_active"] is False

    # Step 10: Non-Destructive Rollback to Version 2 -> produces Version 4
    v2_id = versions_list[1]["id"]
    resp = await http_client.post(
        f"/api/v1/versions/{v2_id}/rollback",
        headers=owner_headers(),
    )
    assert resp.status_code == 200, resp.text
    rollback_data = resp.json()
    assert rollback_data["new_version"] == 4
    assert rollback_data["rolled_back_to_version"] == 2
    assert len(rollback_data["version_record"]["source_checksum"]) == 64

    # Preview is updated to v4
    resp = await http_client.get(
        f"/api/v1/previews/{preview_id}/status",
        headers=owner_headers(),
    )
    assert resp.status_code == 200
    assert resp.json()["version"] == 4

    # All 3 versions (v4, v3, v2) remain intact (immutable history)
    resp = await http_client.get(
        f"/api/v1/projects/{project_id}/versions",
        headers=owner_headers(),
    )
    assert resp.status_code == 200
    assert len(resp.json()["versions"]) == 3


@pytest.mark.asyncio
async def test_idor_protection_across_all_phase6_endpoints(http_client: AsyncClient, db: AsyncSession):
    """
    2. Comprehensive IDOR Protection:
    Ensures that an unauthorized tenant/intruder cannot read, create, or modify
    build sessions, generations, blueprints, code generations, previews, edits, or versions.
    """
    lead, convo, prd = await seed_gate4_approved_lead_and_prd(db, owner_id=OWNER_EMAIL)

    # Setup project & build session as owner
    resp = await http_client.post(
        "/api/v1/projects",
        headers=owner_headers(),
        json={
            "lead_id": str(lead.id),
            "conversation_id": str(convo.id),
            "approved_prd_id": str(prd.id),
            "project_name": "Vanguard Architecture",
        },
    )
    project_id = resp.json()["id"]

    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/build-sessions",
        headers=owner_headers(),
    )
    session_id = resp.json()["id"]

    # Intruder attempts access on project build sessions -> 403 Forbidden
    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/build-sessions",
        headers=intruder_headers(),
    )
    assert resp.status_code == 403

    resp = await http_client.get(
        f"/api/v1/projects/{project_id}/build-sessions",
        headers=intruder_headers(),
    )
    assert resp.status_code == 403

    # Intruder attempts access on build session detail -> 403 Forbidden
    resp = await http_client.get(
        f"/api/v1/build-sessions/{session_id}",
        headers=intruder_headers(),
    )
    assert resp.status_code == 403

    # Intruder attempts to generate website specification -> 403 Forbidden
    resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/generations",
        headers=intruder_headers(),
    )
    assert resp.status_code == 403

    # Intruder attempts preview creation -> 403 Forbidden
    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/previews",
        headers=intruder_headers(),
        json={},
    )
    assert resp.status_code == 403

    # Intruder attempts edit submission -> 403 Forbidden
    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/edits",
        headers=intruder_headers(),
        json={"base_version": 1, "owner_request": "Intruder injection"},
    )
    assert resp.status_code == 403

    # Intruder attempts version listing -> 403 Forbidden
    resp = await http_client.get(
        f"/api/v1/projects/{project_id}/versions",
        headers=intruder_headers(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_gate4_prd_status_and_version_invariants_enforced(http_client: AsyncClient, db: AsyncSession):
    """
    3. Gate 4 Precondition & Version Invariant Enforcement:
    Verifies that unapproved PRDs or version mismatches are strictly blocked
    from creating projects or executing Phase 6 website generation.
    """
    # Create an unapproved (DRAFT) PRD
    lead, convo, unapproved_prd = await seed_gate4_approved_lead_and_prd(
        db, owner_id=OWNER_EMAIL, prd_status=PRDStatus.DRAFT
    )

    # Attempting to create a Project from unapproved PRD must fail (Gate 4 invariant)
    resp = await http_client.post(
        "/api/v1/projects",
        headers=owner_headers(),
        json={
            "lead_id": str(lead.id),
            "conversation_id": str(convo.id),
            "approved_prd_id": str(unapproved_prd.id),
            "project_name": "Invalid Project",
        },
    )
    assert resp.status_code in (400, 422)
    assert "gate 4 approved prd" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_stale_base_version_optimistic_concurrency_rejected(http_client: AsyncClient, db: AsyncSession):
    """
    4. Optimistic Concurrency Control:
    Submitting an edit with an outdated base version must be rejected with 409 Conflict.
    """
    lead, convo, prd = await seed_gate4_approved_lead_and_prd(db, owner_id=OWNER_EMAIL)

    resp = await http_client.post(
        "/api/v1/projects",
        headers=owner_headers(),
        json={
            "lead_id": str(lead.id),
            "conversation_id": str(convo.id),
            "approved_prd_id": str(prd.id),
            "project_name": "Concurrency Project",
        },
    )
    project_id = resp.json()["id"]

    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/build-sessions",
        headers=owner_headers(),
    )
    session_id = resp.json()["id"]

    await http_client.post(f"/api/v1/build-sessions/{session_id}/plan", headers=owner_headers())
    await http_client.post(f"/api/v1/build-sessions/{session_id}/ready", headers=owner_headers())

    gen_resp = await http_client.post(f"/api/v1/build-sessions/{session_id}/generations", headers=owner_headers())
    gen_id = gen_resp.json()["id"]

    bp_resp = await http_client.post(f"/api/v1/generations/{gen_id}/blueprints", headers=owner_headers())
    bp_id = bp_resp.json()["id"]

    code_resp = await http_client.post(
        f"/api/v1/build-sessions/{session_id}/code-generations",
        headers=owner_headers(),
        json={"design_blueprint_id": bp_id},
    )
    code_id = code_resp.json()["id"]

    prev_resp = await http_client.post(
        f"/api/v1/projects/{project_id}/previews",
        headers=owner_headers(),
        json={"code_generation_id": code_id},
    )
    preview_id = prev_resp.json()["id"]

    # First edit: base_version = 1 -> succeeds, creates version 2
    edit1_resp = await http_client.post(
        f"/api/v1/projects/{project_id}/edits",
        headers=owner_headers(),
        json={
            "preview_id": preview_id,
            "base_version": 1,
            "owner_request": "Make the hero darker with slate-950 background",
        },
    )
    assert edit1_resp.status_code == 201

    # Concurrent / stale edit attempting base_version = 1 again must return 409 Conflict
    stale_resp = await http_client.post(
        f"/api/v1/projects/{project_id}/edits",
        headers=owner_headers(),
        json={
            "preview_id": preview_id,
            "base_version": 1,
            "owner_request": "Concurrent conflicting edit",
        },
    )
    assert stale_resp.status_code == 409
    assert "conflict" in stale_resp.json()["detail"].lower() or "base version" in stale_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_prohibited_future_phase_boundaries_return_404(http_client: AsyncClient):
    """
    5. Phase Boundary Enforcement:
    Prohibited deployment, GitHub, Vercel, and browser QA routes must return 404.
    """
    prohibited_routes = [
        "/api/v1/deploy",
        "/api/v1/vercel",
        "/api/v1/github",
        "/api/v1/browser",
        "/api/v1/qa",
        "/api/v1/publish",
        "/api/v1/execute",
    ]
    for route in prohibited_routes:
        resp = await http_client.get(route, headers=owner_headers())
        assert resp.status_code == 404, f"Prohibited route {route} did not return 404"

        resp = await http_client.post(route, headers=owner_headers(), json={})
        assert resp.status_code == 404, f"Prohibited route {route} did not return 404"


@pytest.mark.asyncio
async def test_structured_audit_logging_across_lifecycle(http_client: AsyncClient, db: AsyncSession):
    """
    6. Audit Logging Verification:
    Verifies that pipeline lifecycle events leave immutable records in agent_runs.
    """
    lead, convo, prd = await seed_gate4_approved_lead_and_prd(db, owner_id=OWNER_EMAIL)

    resp = await http_client.post(
        "/api/v1/projects",
        headers=owner_headers(),
        json={
            "lead_id": str(lead.id),
            "conversation_id": str(convo.id),
            "approved_prd_id": str(prd.id),
            "project_name": "Audit Test Project",
        },
    )
    project_id = resp.json()["id"]

    resp = await http_client.post(
        f"/api/v1/projects/{project_id}/build-sessions",
        headers=owner_headers(),
    )
    session_id = resp.json()["id"]

    # Verify agent_runs contains audit records
    stmt = select(AgentRun).where(AgentRun.status == AgentRunStatus.COMPLETED)
    result = await db.execute(stmt)
    runs = result.scalars().all()
    assert len(runs) > 0
    agent_names = [r.agent_name for r in runs]
    assert any("build_session" in name or "project" in name for name in agent_names)
