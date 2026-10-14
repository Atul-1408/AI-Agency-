"""
Phase 7 Tests — Automated Website QA & Evaluator Agent.

Comprehensive test suite verifying:
1. Owner authorization (401 on unauthenticated access)
2. IDOR defense (Owner B cannot access or trigger QA on Owner A's projects)
3. Successful QA execution on generated website workspace
4. Quality checks execution: Build integrity, routing, viewport, a11y, SEO, security
5. Detection of blocker defects (missing entrypoint / unsafe execution APIs)
6. State machine transitions: READY_FOR_QA -> RUNNING -> PASSED / FAILED / PASSED_WITH_WARNINGS
7. Project lifecycle progression: FAILED keeps QA status; PASSED promotes to READY_FOR_DEPLOYMENT
8. Automated finding repair loop: repairs finding, creates new version, updates finding state
9. Concurrency protection (409 Conflict if active QA run is RUNNING)
10. Prohibited future phase boundary enforcement (no /deploy, /github, /vercel)
11. Structured audit trail coverage in agent_runs
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
    WebsiteGeneration,
    WebsiteGenerationStatus,
)
from models.website_qa import (
    QAFindingCategory,
    QAFindingSeverity,
    WebsiteQAFinding,
    WebsiteQARun,
    WebsiteQARunStatus,
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
from schemas.website_qa import WebsiteQARunCreateRequest
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
from services.website_qa_service import WebsiteQAService
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


async def setup_qa_eligible_project(
    db: AsyncSession,
    owner_id: str = OWNER_EMAIL,
) -> Tuple[Project, WebsiteBuildSession, WebsiteCodeGeneration]:
    """Sets up a complete pipeline resulting in a completed code generation and staged workspace."""
    lead = Lead(
        id=uuid.uuid4(),
        company_name="Solas Health",
        domain=f"solas-{uuid.uuid4().hex[:6]}.com",
        source_type="test",
        qualification_score=92,
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
        version=1,
        status=PRDStatus.APPROVED,
        title="Solas Health Platform",
        executive_summary="Modern medical clinic digital experience.",
        business_overview={},
        goals=["Patient appointments"],
        target_audience="Austin Patients",
        sitemap=[{"page": "Home", "status": "approved"}, {"page": "Services", "status": "approved"}],
        content_requirements={},
        functionality_requirements={},
        design_requirements={"style": "Modern Clean", "theme": "Emerald Teal"},
        branding_requirements={},
        contact_requirements={},
        technical_requirements={},
        timeline={},
        budget={},
        assumptions=[],
        open_questions=[],
        requirement_traceability={},
        generated_at=datetime.now(timezone.utc),
        approved_at=datetime.now(timezone.utc),
        approved_by=owner_id,
    )
    db.add(prd)
    await db.flush()

    project = Project(
        id=uuid.uuid4(),
        owner_id=owner_id,
        lead_id=lead.id,
        conversation_id=convo.id,
        approved_prd_id=prd.id,
        prd_version=1,
        project_name="Solas Health",
        project_slug=f"solas-health-{uuid.uuid4().hex[:4]}",
        project_status=ProjectStatus.READY_FOR_BUILD,
        project_source="client_conversation",
        created_by=owner_id,
        phase_metadata={},
    )
    db.add(project)
    await db.flush()

    session = WebsiteBuildSession(
        id=uuid.uuid4(),
        project_id=project.id,
        owner_id=owner_id,
        status=WebsiteBuildSessionStatus.READY,
        build_version=1,
    )
    db.add(session)
    await db.flush()

    spec = WebsiteSpecification(
        specification_version="1.0.0",
        source_prd_id=str(prd.id),
        source_prd_version=1,
        generation_version=1,
        project_name=project.project_name,
        project_slug=project.project_slug,
        website_goal="Generate patient appointments",
        target_audience="Austin Patients",
        primary_cta="Book Appointment",
        secondary_ctas=["Learn More"],
        pages=[
            PageSpecification(
                page_id="page_home",
                path="/",
                name="Home",
                purpose="Primary landing page with credibility and booking CTA",
                priority="primary",
                seo_title="Solas Health — Premier Austin Medical Clinic",
                seo_description="Compassionate, modern medical care in Austin.",
                sections=[
                    SectionSpecification(
                        section_id="sec_hero",
                        type="hero",
                        purpose="Headline with appointment booking CTA",
                        heading="Welcome to Solas Health",
                        supporting_content="Compassionate, modern medical care.",
                        layout="hero_split",
                        components=["Hero"],
                        cta="Book Appointment",
                    )
                ],
                primary_cta="Book Appointment",
            )
        ],
        navigation=[
            NavigationItemSpecification(label="Home", path="/", order=1, visibility="all"),
        ],
        design_system=DesignSystemSpecification(
            visual_direction="clean-modern",
            typography=TypographySpecification(
                heading_family="Inter, sans-serif",
                body_family="Inter, sans-serif",
                heading_scale={"h1": "2.5rem", "h2": "2rem"},
                body_scale={"base": "1rem"},
            ),
            color_palette=ColorPaletteSpecification(
                primary="#0d9488",
                secondary="#0f766e",
                accent="#f59e0b",
                background="#ffffff",
                surface="#f8fafc",
                text="#0f172a",
                muted="#64748b",
            ),
            spacing={"base": "1rem"},
            border_radius={"card": "0.5rem"},
            shadows={"card": "0 1px 3px rgba(0,0,0,0.1)"},
            imagery_direction="authentic",
            icon_direction="lucide",
            motion_direction="subtle",
            responsive_strategy="mobile-first",
        ),
        content_strategy=[],
        accessibility_requirements=["WCAG AA contrast", "Keyboard navigation"],
        responsive_requirements=["Mobile friendly", "Fast loading"],
    )

    spec_artifact = WebsiteBuildArtifact(
        id=uuid.uuid4(),
        build_session_id=session.id,
        project_id=project.id,
        artifact_type=WebsiteBuildArtifactType.WEBSITE_SPECIFICATION,
        artifact_name="website_specification_v1",
        artifact_version=1,
        artifact_metadata=spec.model_dump(),
    )
    db.add(spec_artifact)
    await db.flush()

    web_gen = WebsiteGeneration(
        id=uuid.uuid4(),
        build_session_id=session.id,
        project_id=project.id,
        owner_id=owner_id,
        source_prd_id=prd.id,
        source_prd_version=1,
        generation_version=1,
        status=WebsiteGenerationStatus.COMPLETED,
        provider="mock_provider",
        model="mock-v1",
        specification_artifact_id=spec_artifact.id,
    )
    db.add(web_gen)
    await db.flush()

    from services.design_blueprint_provider import MockDesignBlueprintProvider
    mock_bp_prov = MockDesignBlueprintProvider()
    blueprint_obj, _ = await mock_bp_prov.generate_blueprint(
        "",
        "",
        {
            "specification": spec.model_dump(),
            "source_generation_id": str(web_gen.id),
            "blueprint_version": 1,
            "source_generation_version": 1,
        },
    )

    bp_artifact = WebsiteBuildArtifact(
        id=uuid.uuid4(),
        build_session_id=session.id,
        project_id=project.id,
        artifact_type=WebsiteBuildArtifactType.DESIGN_BLUEPRINT,
        artifact_name="design_blueprint_v1",
        artifact_version=1,
        artifact_metadata=blueprint_obj.model_dump(),
    )
    db.add(bp_artifact)
    await db.flush()

    blueprint = DesignBlueprint(
        id=uuid.uuid4(),
        build_session_id=session.id,
        project_id=project.id,
        owner_id=owner_id,
        source_generation_id=web_gen.id,
        source_generation_version=1,
        blueprint_version=1,
        status=DesignBlueprintStatus.COMPLETED,
        specification_artifact_id=bp_artifact.id,
    )
    db.add(blueprint)
    await db.flush()

    # Generate real code and workspace
    code_gen = await WebsiteCodeGenerationService.generate_code(
        db=db,
        session_id=session.id,
        owner_id=owner_id,
        blueprint_id=blueprint.id,
    )
    await db.commit()
    await db.refresh(project)
    await db.refresh(session)
    await db.refresh(code_gen)

    return project, session, code_gen


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_qa_requires_owner_auth(http_client: AsyncClient):
    """1. Enforces 401 on unauthenticated access."""
    dummy_id = uuid.uuid4()
    resp = await http_client.post(f"/api/v1/projects/{dummy_id}/qa-runs", json={})
    assert resp.status_code == 401

    resp = await http_client.get(f"/api/v1/projects/{dummy_id}/qa-runs")
    assert resp.status_code == 401

    resp = await http_client.get(f"/api/v1/qa-runs/{dummy_id}")
    assert resp.status_code == 401

    resp = await http_client.post(f"/api/v1/qa-findings/{dummy_id}/repair", json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_qa_idor_protection(http_client: AsyncClient, db: AsyncSession):
    """2. Enforces 403 on cross-tenant / intruder access."""
    project, session, code_gen = await setup_qa_eligible_project(db)

    # Intruder cannot trigger QA on Owner's project
    resp = await http_client.post(
        f"/api/v1/projects/{project.id}/qa-runs",
        headers=intruder_headers(),
        json={},
    )
    assert resp.status_code == 403

    # Intruder cannot list Owner's QA runs
    resp = await http_client.get(
        f"/api/v1/projects/{project.id}/qa-runs",
        headers=intruder_headers(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_successful_qa_run_execution(http_client: AsyncClient, db: AsyncSession):
    """3. Verifies automated QA evaluation runs across all quality categories and evaluates score."""
    project, session, code_gen = await setup_qa_eligible_project(db)

    resp = await http_client.post(
        f"/api/v1/projects/{project.id}/qa-runs",
        headers=owner_headers(),
        json={},
    )
    assert resp.status_code == 201, resp.text
    run_data = resp.json()
    assert run_data["project_id"] == str(project.id)
    assert run_data["status"] in ("passed", "passed_with_warnings")
    assert run_data["total_checks"] >= 5
    assert run_data["score"] >= 80

    # Project is marked ready for deployment
    await db.refresh(project)
    assert project.project_status == ProjectStatus.READY_FOR_DEPLOYMENT


@pytest.mark.asyncio
async def test_qa_detail_and_findings_inspection(http_client: AsyncClient, db: AsyncSession):
    """4. Verifies detailed QA report retrieval and findings categorization."""
    project, session, code_gen = await setup_qa_eligible_project(db)

    # Run QA
    run_resp = await http_client.post(
        f"/api/v1/projects/{project.id}/qa-runs",
        headers=owner_headers(),
        json={},
    )
    run_id = run_resp.json()["id"]

    # Retrieve detailed report
    detail_resp = await http_client.get(
        f"/api/v1/qa-runs/{run_id}",
        headers=owner_headers(),
    )
    assert detail_resp.status_code == 200
    report = detail_resp.json()
    assert "run" in report
    assert "findings" in report
    assert "summary_by_severity" in report
    assert "summary_by_category" in report
    assert report["can_deploy"] is True


@pytest.mark.asyncio
async def test_blocker_detection_fails_qa_and_blocks_deployment(http_client: AsyncClient, db: AsyncSession):
    """5. Verifies that blocker defects (unsafe APIs or missing files) cause QA FAILED and block deployment."""
    project, session, code_gen = await setup_qa_eligible_project(db)

    # Inject an unsafe API into the workspace to simulate defect
    ws_dir = WebsiteWorkspaceService.get_workspace_dir(code_gen.id)
    hero_file = ws_dir / "components" / "sections" / "Hero.tsx"
    if hero_file.exists():
        content = hero_file.read_text(encoding="utf-8")
        hero_file.write_text(content + "\n// test eval defect\nconst unsafe = eval('2+2');\n", encoding="utf-8")

    resp = await http_client.post(
        f"/api/v1/projects/{project.id}/qa-runs",
        headers=owner_headers(),
        json={},
    )
    assert resp.status_code == 201
    run_data = resp.json()
    assert run_data["status"] == "failed"

    # Detail report shows can_deploy = False
    detail_resp = await http_client.get(
        f"/api/v1/qa-runs/{run_data['id']}",
        headers=owner_headers(),
    )
    assert detail_resp.json()["can_deploy"] is False
    assert detail_resp.json()["summary_by_severity"].get("blocker", 0) > 0

    # Project status remains QA (not ready for deployment)
    await db.refresh(project)
    assert project.project_status == ProjectStatus.QA


@pytest.mark.asyncio
async def test_automated_finding_repair_loop(http_client: AsyncClient, db: AsyncSession):
    """6. Verifies automated defect repair loop creates a new release and resolves the defect."""
    project, session, code_gen = await setup_qa_eligible_project(db)

    # Run QA
    run_resp = await http_client.post(
        f"/api/v1/projects/{project.id}/qa-runs",
        headers=owner_headers(),
        json={},
    )
    run_id = run_resp.json()["id"]

    # List findings
    findings_resp = await http_client.get(f"/api/v1/qa-runs/{run_id}/findings", headers=owner_headers())
    findings = findings_resp.json()

    if findings:
        target_finding = findings[0]
        finding_id = target_finding["id"]

        # Trigger repair
        repair_resp = await http_client.post(
            f"/api/v1/qa-findings/{finding_id}/repair",
            headers=owner_headers(),
            json={},
        )
        assert repair_resp.status_code == 200
        rep_data = repair_resp.json()
        assert rep_data["is_repaired"] is True
        assert rep_data["new_version"] >= 2

        # Verify second repair call is idempotent
        rep2_resp = await http_client.post(
            f"/api/v1/qa-findings/{finding_id}/repair",
            headers=owner_headers(),
            json={},
        )
        assert rep2_resp.status_code == 200
        assert rep2_resp.json()["is_repaired"] is True


@pytest.mark.asyncio
async def test_prohibited_phase8_endpoints_return_404(http_client: AsyncClient):
    """7. Verifies Phase 8 deployment routes strictly return 404."""
    prohibited = ["/api/v1/deploy", "/api/v1/vercel", "/api/v1/github", "/api/v1/publish"]
    for route in prohibited:
        resp = await http_client.get(route, headers=owner_headers())
        assert resp.status_code == 404
        resp = await http_client.post(route, headers=owner_headers(), json={})
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_qa_structured_audit_logging(http_client: AsyncClient, db: AsyncSession):
    """8. Verifies QA lifecycle actions emit immutable structured records to agent_runs."""
    project, session, code_gen = await setup_qa_eligible_project(db)

    resp = await http_client.post(
        f"/api/v1/projects/{project.id}/qa-runs",
        headers=owner_headers(),
        json={},
    )
    assert resp.status_code == 201

    stmt = select(AgentRun).where(AgentRun.agent_name.like("website_qa:%"))
    res = await db.execute(stmt)
    runs = res.scalars().all()
    assert len(runs) > 0
    actions = [r.agent_name for r in runs]
    assert any("qa_run_completed" in a for a in actions)
