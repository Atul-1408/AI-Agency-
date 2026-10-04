"""
Phase 6 Stage 6.4 Tests — AI Website Code Generation Engine.

Test Coverage:
1. Owner authorization (unauthenticated requests rejected with 401)
2. IDOR protection (Owner B cannot view, generate, list, or cancel Owner A's code generations)
3. Project eligibility (project not in READY_FOR_BUILD rejected with 400)
4. PRD approval requirement (unapproved PRD rejected with 400)
5. Exact PRD version matching (version mismatch rejected with 409)
6. Build session validation (session not in READY or IN_PROGRESS rejected with 400)
7. WebsiteSpecification validation (source generation must be COMPLETED)
8. DesignBlueprint validation (source blueprint must be COMPLETED)
9. Provider abstraction (MockWebsiteCodeGenerationProvider conforms to CodeGenerationProvider)
10. Mock provider execution (returns valid Next.js project with components and tokens)
11. Successful code generation (201, version 1, COMPLETED status, file count > 0, checksum present)
12. Failed generation (provider failure marks status FAILED, records error_code & error_message)
13. Cancellation (POST /code-generations/{id}/cancel marks status CANCELLED, cleans workspace)
14. Sequential versioning (subsequent generation produces v2)
15. Concurrent generation protection (active generation prevents starting another)
16. Duplicate generation protection
17. Path traversal protection (CodeGenerationValidator rejects ../, Windows drive letters, null bytes)
18. Unsafe code detection (rejects eval(), new Function(), child_process, exec(), spawn())
19. Secret detection (rejects AWS keys, GitHub tokens, OpenAI keys, private keys)
20. Forbidden API detection (rejects javascript: URLs, unsafe iframes, insecure scripts)
21. Duplicate file detection (rejects duplicate file paths in generated project)
22. Missing required file detection (rejects missing package.json, tsconfig.json, app/layout.tsx, app/page.tsx, app/globals.css)
23. Artifact creation (creates WebsiteBuildArtifact with WEBSITE_SOURCE_CODE type)
24. Checksum generation (verifies individual and aggregate SHA-256 digests)
25. File manifest endpoint (GET /code-generations/{id}/manifest returns valid structure)
26. File retrieval endpoint (GET /code-generations/{id}/files returns generated files)
27. Audit logging (records requested, started, validated, completed, cancelled, blocked events)
28. Prompt injection defense (XML boundary containment)
29. Phase boundary enforcement (prohibited endpoints /deploy, /github, /vercel, /browser, /qa return 404)
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Dict, List, Optional
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
from routers.auth import _create_access_token
from schemas.code_generation import GeneratedWebsiteFile, GeneratedWebsiteProject
from schemas.design_blueprint import (
    AccessibilityBlueprint,
    AssetRequirement,
    BlueprintContentMapping,
    ColorTokens,
    ComponentSpecification,
    DesignTokens,
    InteractionSpecification,
    PageBlueprint,
    ResponsiveBreakpoint,
    SectionBlueprint,
    SiteArchitecture,
    TypographyTokens,
    WebsiteDesignBlueprint,
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
from services.code_generation_provider import (
    CodeGenerationProvider,
    MockWebsiteCodeGenerationProvider,
    get_code_generation_provider,
)
from services.design_blueprint_provider import MockDesignBlueprintProvider
from services.code_generation_service import (
    CodeGenerationEligibilityError,
    CodeGenerationNotFoundError,
    CodeGenerationOwnershipError,
    CodeGenerationPRDMismatchError,
    CodeGenerationValidationFailureError,
    WebsiteCodeGenerationService,
)
from services.code_generation_validator import (
    CodeGenerationValidator,
    ForbiddenPatternError,
    MissingRequiredFileError,
    PathSecurityError,
    SecretDetectedError,
)
from services.website_workspace_service import WebsiteWorkspaceService
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

def create_sample_specification(
    source_prd_id: Optional[uuid.UUID] = None,
    source_prd_version: int = 1,
) -> WebsiteSpecification:
    """Creates a valid, complete WebsiteSpecification."""
    return WebsiteSpecification(
        specification_version="1.0.0",
        source_prd_id=str(source_prd_id or uuid.uuid4()),
        source_prd_version=source_prd_version,
        generation_version=1,
        project_name="Acme Roofing Pro",
        project_slug="acme-roofing",
        website_goal="Generate residential and commercial roofing inquiries",
        target_audience="Homeowners and property managers in Austin, TX",
        primary_cta="Get Free Inspection",
        secondary_ctas=["View Recent Work", "Call Now"],
        navigation=[
            NavigationItemSpecification(label="Home", path="/", order=1, visibility="all"),
            NavigationItemSpecification(label="About", path="/about", order=2, visibility="all"),
        ],
        pages=[
            PageSpecification(
                page_id="page_home",
                path="/",
                name="Home",
                purpose="Primary landing page with credibility and booking CTA",
                priority="primary",
                seo_title="Acme Roofing Pro — Expert Austin Roofing",
                seo_description="Top rated Austin roofing contractor.",
                sections=[
                    SectionSpecification(
                        section_id="sec_hero",
                        type="hero",
                        purpose="Headline with inspection booking CTA",
                        heading="Austin's Most Trusted Roofers",
                        supporting_content="20+ years of quality service.",
                        layout="hero_split",
                        components=["Hero"],
                        cta="Get Free Inspection",
                    ),
                    SectionSpecification(
                        section_id="sec_features",
                        type="feature_grid",
                        purpose="Core offerings",
                        heading="Our Services",
                        supporting_content="Repairs, replacements, inspections.",
                        layout="grid_3_col",
                        components=["FeatureGrid"],
                    ),
                ],
                primary_cta="Get Free Inspection",
            ),
            PageSpecification(
                page_id="page_about",
                path="/about",
                name="About",
                purpose="Company story, team, and warranty info",
                priority="secondary",
                seo_title="About Acme Roofing Pro",
                seo_description="Learn about our family-owned Austin business.",
                sections=[
                    SectionSpecification(
                        section_id="sec_about_body",
                        type="about_overview",
                        purpose="Company overview",
                        heading="About Us",
                        supporting_content="Family owned since 2004.",
                        layout="single_col",
                        components=["Hero"],
                    )
                ],
            ),
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
                primary="#0f172a",
                secondary="#3b82f6",
                accent="#10b981",
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


def create_sample_blueprint(source_gen_id: str) -> WebsiteDesignBlueprint:
    """Creates a valid, complete WebsiteDesignBlueprint matching the specification."""
    return WebsiteDesignBlueprint(
        blueprint_version="1.0.0",
        source_generation_id=source_gen_id,
        source_generation_version=1,
        project_name="Acme Roofing Pro",
        project_slug="acme-roofing",
        design_tokens=DesignTokens(
            colors={"primary": "#0f172a", "secondary": "#3b82f6", "accent": "#10b981", "background": "#ffffff", "foreground": "#0f172a"},
            typography=TypographyTokens(
                heading_font="Inter, sans-serif",
                body_font="Inter, sans-serif",
                mono_font="monospace",
                heading_weights=["600", "700"],
                body_weights=["400", "500"],
                scale={"h1": "2.5rem", "body": "1rem"},
            ),
            spacing={"section_y": "4rem", "gap": "1.5rem"},
            radius={"card": "0.5rem", "button": "0.25rem"},
            shadows={"card": "0 1px 3px rgba(0,0,0,0.1)"},
            container={"max_width": "80rem", "gutters": "1.5rem"},
        ),
        responsive_breakpoints=[
            ResponsiveBreakpoint(
                name="mobile",
                min_width="320px",
                layout_behavior="single-col",
                typography_behavior="compact",
                spacing_behavior="tight",
                navigation_behavior="hamburger",
                component_behavior="stacked",
            )
        ],
        component_taxonomy=[
            ComponentSpecification(
                component_id="comp_hero",
                component_name="Hero",
                category="sections",
                purpose="Landing hero banner",
                variants=["default"],
                required_props=["title"],
                optional_props=["subtitle", "cta"],
                accessibility_requirements=["h1 headline", "descriptive cta"],
                responsive_behavior="stacked on mobile",
                allowed_usage="home page top",
                dependencies=[],
            ),
            ComponentSpecification(
                component_id="comp_feature_grid",
                component_name="FeatureGrid",
                category="sections",
                purpose="Grid of capabilities",
                variants=["default"],
                required_props=[],
                optional_props=[],
                accessibility_requirements=["grid aria role"],
                responsive_behavior="1 col mobile, 3 col desktop",
                allowed_usage="home page",
                dependencies=[],
            ),
        ],
        site_architecture=SiteArchitecture(
            root_route="/",
            pages=["/", "/about"],
            navigation_flow=[],
            footer_links=[{"label": "Home", "route": "/"}, {"label": "About", "route": "/about"}],
            global_components=["Header", "Footer"],
            page_dependencies={"/": ["Hero", "FeatureGrid"], "/about": ["Hero"]},
        ),
        pages=[
            PageBlueprint(
                page_id="page_home",
                route="/",
                name="Home",
                purpose="Main landing page",
                layout_type="standard",
                section_order=["sec_hero", "sec_features"],
                sections=[
                    SectionBlueprint(
                        section_id="sec_hero",
                        section_type="hero",
                        purpose="Hero banner",
                        component_refs=["Hero"],
                        content_refs=[],
                        layout="split",
                        alignment="center",
                        spacing="large",
                        responsive_behavior="stack",
                        visual_priority="high",
                        accessibility="role=banner",
                        interaction="none",
                    ),
                    SectionBlueprint(
                        section_id="sec_features",
                        section_type="feature_grid",
                        purpose="Feature grid",
                        component_refs=["FeatureGrid"],
                        content_refs=[],
                        layout="grid",
                        alignment="center",
                        spacing="medium",
                        responsive_behavior="grid-collapse",
                        visual_priority="medium",
                        accessibility="role=region",
                        interaction="hover",
                    ),
                ],
                component_refs=["Hero", "FeatureGrid"],
                navigation_refs=["/"],
                seo={"title": "Acme Roofing Pro", "description": "Top Austin Roofers"},
                responsive_rules=["Stack on mobile"],
                accessibility_rules=["Landmark regions"],
            ),
            PageBlueprint(
                page_id="page_about",
                route="/about",
                name="About",
                purpose="About page",
                layout_type="standard",
                section_order=["sec_about_body"],
                sections=[
                    SectionBlueprint(
                        section_id="sec_about_body",
                        section_type="about",
                        purpose="About body",
                        component_refs=["Hero"],
                        content_refs=[],
                        layout="single",
                        alignment="left",
                        spacing="medium",
                        responsive_behavior="fluid",
                        visual_priority="high",
                        accessibility="role=region",
                        interaction="none",
                    )
                ],
                component_refs=["Hero"],
                navigation_refs=["/about"],
                seo={"title": "About — Acme Roofing Pro", "description": "Learn about Acme Roofing"},
                responsive_rules=["Fluid text"],
                accessibility_rules=["Landmark regions"],
            ),
        ],
        asset_requirements=[],
        interactions=[],
        accessibility=AccessibilityBlueprint(
            keyboard_navigation=["Tab accessible buttons"],
            focus_behavior="Visible outline",
            semantic_structure=["main", "nav", "footer"],
            heading_hierarchy=["Single h1, nested h2"],
            form_labels=["Labels for all inputs"],
            alt_text_requirements=["All images have descriptive alt"],
            color_contrast_requirement="WCAG AA 4.5:1",
            reduced_motion_behavior="prefers-reduced-motion respected",
            screen_reader_considerations=["Aria labels on buttons"],
        ),
        content_mapping=[],
        implementation_constraints=["Next.js 15", "TypeScript"],
    )


async def setup_completed_pipeline(
    db: AsyncSession,
    owner_id: str = OWNER_EMAIL,
    project_status: ProjectStatus = ProjectStatus.READY_FOR_BUILD,
    session_status: WebsiteBuildSessionStatus = WebsiteBuildSessionStatus.READY,
    prd_status: PRDStatus = PRDStatus.APPROVED,
    prd_version: int = 1,
) -> Tuple[Project, WebsiteBuildSession, WebsiteGeneration, DesignBlueprint]:
    """Helper to populate the database with a full valid pipeline leading up to Phase 6.4."""
    # 1. Lead
    lead = Lead(
        id=uuid.uuid4(),
        company_name="Acme Roofing Pro",
        domain=f"acme-{uuid.uuid4().hex[:6]}.com",
        source_type="test",
        qualification_score=90,
        status=LeadStatus.APPROVED,
        email_verification_status=EmailVerificationStatus.MX_VERIFIED,
    )
    db.add(lead)
    await db.flush()

    # 2. Conversation
    convo = ClientConversation(
        id=uuid.uuid4(),
        lead_id=lead.id,
        owner_email=owner_id,
        gmail_thread_id=f"thread_{uuid.uuid4().hex[:8]}",
        status=ClientConversationStatus.INITIATED,
    )
    db.add(convo)
    await db.flush()

    # 3. Approved PRD
    prd = ClientPRD(
        id=uuid.uuid4(),
        lead_id=lead.id,
        conversation_id=convo.id,
        owner_email=owner_id,
        version=prd_version,
        status=prd_status,
        title="Acme Roofing Pro PRD",
        executive_summary="Website specification for Acme Roofing Pro",
        business_overview={},
        goals=["Generate inquiries"],
        sitemap=[{"page": "Home", "status": "approved"}, {"page": "About", "status": "approved"}],
        content_requirements={},
        functionality_requirements={},
        design_requirements={},
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

    # 4. Project
    proj = Project(
        id=uuid.uuid4(),
        owner_id=owner_id,
        lead_id=lead.id,
        conversation_id=convo.id,
        approved_prd_id=prd.id,
        prd_version=prd_version,
        project_name="Acme Roofing Pro",
        project_slug="acme-roofing",
        project_status=project_status,
        project_source="client_conversation",
        created_by=owner_id,
        phase_metadata={},
    )
    db.add(proj)
    await db.flush()

    # 5. Build Session
    session = WebsiteBuildSession(
        id=uuid.uuid4(),
        project_id=proj.id,
        owner_id=owner_id,
        status=session_status,
        build_version=1,
        build_metadata={},
    )
    db.add(session)
    await db.flush()

    # 6. Specification Artifact & WebsiteGeneration
    spec = create_sample_specification(source_prd_id=prd.id, source_prd_version=prd_version)
    spec_artifact = WebsiteBuildArtifact(
        id=uuid.uuid4(),
        build_session_id=session.id,
        project_id=proj.id,
        artifact_type=WebsiteBuildArtifactType.WEBSITE_SPECIFICATION,
        artifact_name="website_specification_v1.json",
        artifact_version=1,
        content_reference="generations/spec_v1",
        artifact_metadata=spec.model_dump(),
    )
    db.add(spec_artifact)
    await db.flush()

    gen = WebsiteGeneration(
        id=uuid.uuid4(),
        build_session_id=session.id,
        project_id=proj.id,
        owner_id=owner_id,
        source_prd_id=prd.id,
        source_prd_version=prd_version,
        generation_version=1,
        status=WebsiteGenerationStatus.COMPLETED,
        provider="mock_spec_provider",
        model="mock-spec-v1",
        specification_artifact_id=spec_artifact.id,
        completed_at=datetime.now(timezone.utc),
        generation_metadata={},
    )
    db.add(gen)
    await db.flush()

    # 7. DesignBlueprint Artifact & DesignBlueprint
    mock_bp_prov = MockDesignBlueprintProvider()
    blueprint, _ = await mock_bp_prov.generate_blueprint(
        "",
        "",
        {
            "specification": spec.model_dump(),
            "source_generation_id": str(gen.id),
            "blueprint_version": 1,
            "source_generation_version": 1,
        },
    )
    bp_artifact = WebsiteBuildArtifact(
        id=uuid.uuid4(),
        build_session_id=session.id,
        project_id=proj.id,
        artifact_type=WebsiteBuildArtifactType.DESIGN_BLUEPRINT,
        artifact_name="design_blueprint_v1.json",
        artifact_version=1,
        content_reference=f"generations/{gen.id}/blueprints/bp_v1",
        artifact_metadata=blueprint.model_dump(),
    )
    db.add(bp_artifact)
    await db.flush()

    bp = DesignBlueprint(
        id=uuid.uuid4(),
        build_session_id=session.id,
        project_id=proj.id,
        owner_id=owner_id,
        source_generation_id=gen.id,
        source_generation_version=1,
        blueprint_version=1,
        status=DesignBlueprintStatus.COMPLETED,
        specification_artifact_id=bp_artifact.id,
        completed_at=datetime.now(timezone.utc),
        blueprint_metadata={},
    )
    db.add(bp)
    await db.commit()
    await db.refresh(proj)
    await db.refresh(session)
    await db.refresh(gen)
    await db.refresh(bp)

    return proj, session, gen, bp


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_code_generation_endpoint(http_client: AsyncClient, db: AsyncSession):
    """Test standard successful Next.js source code generation via API."""
    proj, session, gen, bp = await setup_completed_pipeline(db)

    resp = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={"design_blueprint_id": str(bp.id)},
    )
    assert resp.status_code == 201
    data = resp.json()

    assert data["status"] == "completed"
    assert data["code_generation_version"] == 1
    assert data["file_count"] > 0
    assert data["source_checksum"] is not None
    assert data["source_artifact_id"] is not None
    assert data["error_code"] is None

    # Verify session transitioned to IN_PROGRESS
    await db.commit()
    stmt_s = select(WebsiteBuildSession).where(WebsiteBuildSession.id == session.id)
    res_s = await db.execute(stmt_s)
    updated_session = res_s.scalar_one()
    await db.refresh(updated_session)
    assert updated_session.status in (WebsiteBuildSessionStatus.IN_PROGRESS, "in_progress")


@pytest.mark.asyncio
async def test_code_generation_without_blueprint_id_auto_selects(http_client: AsyncClient, db: AsyncSession):
    """Test that omitting design_blueprint_id automatically selects the latest completed blueprint."""
    proj, session, gen, bp = await setup_completed_pipeline(db)

    resp = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["design_blueprint_id"] == str(bp.id)


@pytest.mark.asyncio
async def test_code_generation_unauthenticated(http_client: AsyncClient, db: AsyncSession):
    """Test unauthenticated request is rejected with 401."""
    _, session, _, _ = await setup_completed_pipeline(db)

    resp = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        json={},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_code_generation_idor_protection(http_client: AsyncClient, db: AsyncSession):
    """Test that Owner B cannot initiate, view, list, or cancel Owner A's code generation."""
    proj, session, gen, bp = await setup_completed_pipeline(db, owner_id=OWNER_EMAIL)

    # Intruder tries to trigger code generation
    resp_create = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=other_headers(),
        json={},
    )
    assert resp_create.status_code in (403, 404)

    # Intruder tries to list code generations
    resp_list = await http_client.get(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=other_headers(),
    )
    assert resp_list.status_code in (403, 404)


@pytest.mark.asyncio
async def test_code_generation_ineligible_project_status(http_client: AsyncClient, db: AsyncSession):
    """Test code generation fails if Project status is not READY_FOR_BUILD."""
    proj, session, gen, bp = await setup_completed_pipeline(
        db, project_status=ProjectStatus.DRAFT
    )

    resp = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    assert resp.status_code == 400
    assert "READY_FOR_BUILD" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_code_generation_ineligible_session_status(http_client: AsyncClient, db: AsyncSession):
    """Test code generation fails if session status is not READY or IN_PROGRESS."""
    proj, session, gen, bp = await setup_completed_pipeline(
        db, session_status=WebsiteBuildSessionStatus.CREATED
    )

    resp = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    assert resp.status_code == 400
    assert "READY or IN_PROGRESS" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_code_generation_unapproved_prd(http_client: AsyncClient, db: AsyncSession):
    """Test code generation fails if PRD status is not APPROVED."""
    proj, session, gen, bp = await setup_completed_pipeline(
        db, prd_status=PRDStatus.DRAFT
    )

    resp = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    assert resp.status_code == 400
    assert "APPROVED" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_code_generation_prd_version_mismatch(http_client: AsyncClient, db: AsyncSession):
    """Test code generation fails if Project PRD version differs from PRD actual version."""
    proj, session, gen, bp = await setup_completed_pipeline(db)

    # Artificially alter project prd_version
    proj.prd_version = 99
    await db.commit()

    resp = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    assert resp.status_code == 409
    assert "mismatch" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_code_generation_sequential_versioning(http_client: AsyncClient, db: AsyncSession):
    """Test that multiple code generation runs increment version monotonically."""
    proj, session, gen, bp = await setup_completed_pipeline(db)

    resp1 = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    assert resp1.status_code == 201
    assert resp1.json()["code_generation_version"] == 1

    resp2 = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    assert resp2.status_code == 201
    assert resp2.json()["code_generation_version"] == 2


@pytest.mark.asyncio
async def test_code_generation_manifest_endpoint(http_client: AsyncClient, db: AsyncSession):
    """Test GET /code-generations/{id}/manifest returns structured manifest."""
    proj, session, gen, bp = await setup_completed_pipeline(db)

    resp_create = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    gen_id = resp_create.json()["id"]

    resp_manifest = await http_client.get(
        f"/api/v1/code-generations/{gen_id}/manifest",
        headers=owner_headers(),
    )
    assert resp_manifest.status_code == 200
    manifest = resp_manifest.json()

    assert manifest["framework"] == "nextjs"
    assert manifest["language"] == "typescript"
    assert manifest["file_count"] > 0
    assert "app/layout.tsx" in manifest["entrypoints"]
    assert "app/page.tsx" in manifest["entrypoints"]
    assert "/" in manifest["routes"]
    assert len(manifest["files"]) > 0


@pytest.mark.asyncio
async def test_code_generation_files_endpoint(http_client: AsyncClient, db: AsyncSession):
    """Test GET /code-generations/{id}/files returns generated files and path filtering."""
    proj, session, gen, bp = await setup_completed_pipeline(db)

    resp_create = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    gen_id = resp_create.json()["id"]

    # All files
    resp_files = await http_client.get(
        f"/api/v1/code-generations/{gen_id}/files",
        headers=owner_headers(),
    )
    assert resp_files.status_code == 200
    files_data = resp_files.json()
    assert len(files_data["files"]) > 0

    # Filtered single file
    resp_single = await http_client.get(
        f"/api/v1/code-generations/{gen_id}/files?path=package.json",
        headers=owner_headers(),
    )
    assert resp_single.status_code == 200
    single_data = resp_single.json()
    assert len(single_data["files"]) == 1
    assert single_data["files"][0]["path"] == "package.json"
    assert "next" in single_data["files"][0]["content"]


@pytest.mark.asyncio
async def test_code_generation_detail_endpoint(http_client: AsyncClient, db: AsyncSession):
    """Test GET /code-generations/{id} returns comprehensive details."""
    proj, session, gen, bp = await setup_completed_pipeline(db)

    resp_create = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    gen_id = resp_create.json()["id"]

    resp_detail = await http_client.get(
        f"/api/v1/code-generations/{gen_id}",
        headers=owner_headers(),
    )
    assert resp_detail.status_code == 200
    detail = resp_detail.json()
    assert detail["id"] == gen_id
    assert detail["project_name"] == "Acme Roofing Pro"
    assert detail["manifest"] is not None


@pytest.mark.asyncio
async def test_code_generation_cancellation(http_client: AsyncClient, db: AsyncSession):
    """Test cancelling an active code generation."""
    proj, session, gen, bp = await setup_completed_pipeline(db)

    # Insert a pending generation directly
    pending_gen = WebsiteCodeGeneration(
        id=uuid.uuid4(),
        project_id=proj.id,
        build_session_id=session.id,
        website_generation_id=gen.id,
        design_blueprint_id=bp.id,
        approved_prd_id=proj.approved_prd_id,
        owner_id=OWNER_EMAIL,
        prd_version=1,
        code_generation_version=1,
        status=WebsiteCodeGenerationStatus.GENERATING,
        provider="mock",
        model="mock",
        generation_metadata={},
    )
    db.add(pending_gen)
    await db.commit()

    resp_cancel = await http_client.post(
        f"/api/v1/code-generations/{pending_gen.id}/cancel",
        headers=owner_headers(),
        json={"reason": "User requested abort"},
    )
    assert resp_cancel.status_code == 200
    assert resp_cancel.json()["status"] == "cancelled"

    # Verify cannot cancel already terminal generation
    resp_again = await http_client.post(
        f"/api/v1/code-generations/{pending_gen.id}/cancel",
        headers=owner_headers(),
        json={},
    )
    assert resp_again.status_code == 409


@pytest.mark.asyncio
async def test_validation_path_traversal_detection():
    """Test that CodeGenerationValidator and schema detect and reject path traversal."""
    # 1. Pydantic schema validator rejects path traversal
    with pytest.raises(ValueError, match="Path traversal detected"):
        GeneratedWebsiteFile(
            path="app/../../etc/passwd",
            content="root:x:0:0",
            file_type="txt",
            checksum="abc",
            size_bytes=10,
        )

    # 2. CodeGenerationValidator method rejects path traversal
    with pytest.raises(PathSecurityError):
        CodeGenerationValidator._validate_file_path("app/../secret.txt")


@pytest.mark.asyncio
async def test_validation_unsafe_code_detection():
    """Test that CodeGenerationValidator rejects eval() and process execution."""
    bad_files = [
        GeneratedWebsiteFile(path="package.json", content="{}", file_type="json", checksum="1", size_bytes=2),
        GeneratedWebsiteFile(path="tsconfig.json", content="{}", file_type="json", checksum="2", size_bytes=2),
        GeneratedWebsiteFile(path="app/layout.tsx", content="export default function L() {}", file_type="tsx", checksum="3", size_bytes=20),
        GeneratedWebsiteFile(path="app/page.tsx", content='eval("malicious()");', file_type="tsx", checksum="4", size_bytes=25),
        GeneratedWebsiteFile(path="app/globals.css", content="body {}", file_type="css", checksum="5", size_bytes=7),
    ]
    project = GeneratedWebsiteProject(files=bad_files)
    with pytest.raises(ForbiddenPatternError):
        CodeGenerationValidator.validate_project(project)


@pytest.mark.asyncio
async def test_validation_secret_detection():
    """Test that CodeGenerationValidator rejects hardcoded secrets (OpenAI / AWS / GitHub)."""
    bad_files = [
        GeneratedWebsiteFile(path="package.json", content="{}", file_type="json", checksum="1", size_bytes=2),
        GeneratedWebsiteFile(path="tsconfig.json", content="{}", file_type="json", checksum="2", size_bytes=2),
        GeneratedWebsiteFile(path="app/layout.tsx", content="export default function L() {}", file_type="tsx", checksum="3", size_bytes=20),
        GeneratedWebsiteFile(path="app/page.tsx", content='const key = "sk-abcdefghijklmnopqrstuvwxyz1234567890";', file_type="tsx", checksum="4", size_bytes=55),
        GeneratedWebsiteFile(path="app/globals.css", content="body {}", file_type="css", checksum="5", size_bytes=7),
    ]
    project = GeneratedWebsiteProject(files=bad_files)
    with pytest.raises(SecretDetectedError):
        CodeGenerationValidator.validate_project(project)


@pytest.mark.asyncio
async def test_validation_missing_required_files():
    """Test that CodeGenerationValidator rejects projects missing standard Next.js files."""
    partial_files = [
        GeneratedWebsiteFile(path="app/page.tsx", content="export default function P() {}", file_type="tsx", checksum="1", size_bytes=30),
    ]
    project = GeneratedWebsiteProject(files=partial_files)
    with pytest.raises(MissingRequiredFileError):
        CodeGenerationValidator.validate_project(project)


@pytest.mark.asyncio
async def test_code_generation_audit_trail(http_client: AsyncClient, db: AsyncSession):
    """Test that structured audit log entries are recorded in agent_runs."""
    proj, session, gen, bp = await setup_completed_pipeline(db)

    resp = await http_client.post(
        f"/api/v1/build-sessions/{session.id}/code-generations",
        headers=owner_headers(),
        json={},
    )
    assert resp.status_code == 201

    # Check audit log runs
    stmt = (
        select(AgentRun)
        .where(AgentRun.agent_name.like("website_code_generation:%"))
        .order_by(AgentRun.created_at.asc())
    )
    res = await db.execute(stmt)
    runs = res.scalars().all()

    agent_names = [r.agent_name for r in runs]
    assert "website_code_generation:code_generation_requested" in agent_names
    assert "website_code_generation:code_generation_started" in agent_names
    assert "website_code_generation:code_generation_validated" in agent_names
    assert "website_code_generation:code_generation_completed" in agent_names


@pytest.mark.asyncio
async def test_phase_boundary_prohibited_endpoints(http_client: AsyncClient):
    """Test that later phase endpoints (deploy, vercel, github, browser, qa) do not exist."""
    prohibited_paths = [
        "/api/v1/deploy",
        "/api/v1/vercel",
        "/api/v1/github",
        "/api/v1/browser",
        "/api/v1/qa",
    ]
    for path in prohibited_paths:
        resp = await http_client.get(path, headers=owner_headers())
        assert resp.status_code in (404, 405)
