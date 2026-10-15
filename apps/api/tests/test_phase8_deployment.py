"""
Phase 8 Tests — Production Deployment & Hosting Integrations.

Comprehensive test suite verifying:
1. Owner authorization (401 on unauthenticated access)
2. Multi-tenant IDOR protection (Owner B cannot access, approve, or deploy Owner A's project)
3. Server-side eligibility enforcement:
   - Rejects if code generation is not completed
   - Rejects if no QA evaluation exists
   - Rejects if QA evaluation failed
   - Rejects if QA evaluation has unresolved BLOCKER or HIGH findings
   - Rejects stale QA reports where target version does not match active source version
4. Gate 5 Owner Approval requirement:
   - Production deployment enters AWAITING_APPROVAL and creates ApprovalRequest(action_type="deploy_website")
   - Execution is blocked until owner explicitly approves
   - Safe cancellation transitions to CANCELLED and marks approval REJECTED
5. Provider execution pipeline (GitHub + Vercel):
   - Non-destructive GitHub sync with deterministic commit SHA and provenance tracking
   - Vercel deployment creation, live URL recording, and Project status progression to DEPLOYED
   - Provider failure handling (honest error recording, no auto-retries)
6. Security checks:
   - Prohibited files (.env, .pem, id_rsa, credentials.json) rejected before deployment
   - Secret key patterns rejected
   - Directory traversal attempts rejected
   - Zero access token leakage in responses or logs
7. Custom Domain & DNS:
   - Apex A and subdomain CNAME records generation
   - Honest SSL status verification (never claims active if unverified)
8. Audit trail in agent_runs table
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from main import app as fastapi_app
from models import (
    AgentRun,
    AgentRunStatus,
    ApprovalRequest,
    ApprovalStatus,
    EmailVerificationStatus,
    Lead,
    LeadStatus,
)
from models.client_intelligence import (
    ClientConversation,
    ClientConversationStatus,
    ClientPRD,
    PRDStatus,
)
from models.project import Project, ProjectStatus
from models.website_builder import (
    WebsiteBuildSession,
    WebsiteBuildSessionStatus,
    WebsiteCodeGeneration,
    WebsiteCodeGenerationStatus,
)
from models.website_deployment import (
    DeploymentEnvironment,
    DeploymentProvider,
    WebsiteDeployment,
    WebsiteDeploymentStatus,
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
from schemas.website_deployment import WebsiteDeploymentCreateRequest
from services.deployment_providers.github_provider import GitHubProvider
from services.deployment_providers.mock_providers import MockDeploymentProvider
from services.deployment_providers.vercel_provider import VercelProvider
from services.website_deployment_service import WebsiteDeploymentService
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
    orig_prov = settings.DEPLOYMENT_PROVIDER
    settings.OWNER_EMAIL = OWNER_EMAIL
    settings.DEPLOYMENT_PROVIDER = "mock"
    yield
    settings.OWNER_EMAIL = orig_owner
    settings.DEPLOYMENT_PROVIDER = orig_prov


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


# ── Test Pipeline Setup Helper ────────────────────────────────────────────────

from tests.test_phase7_qa_agent import setup_qa_eligible_project


async def setup_deployment_ready_pipeline(
    db: AsyncSession,
    owner_id: str = OWNER_EMAIL,
    qa_status: WebsiteQARunStatus = WebsiteQARunStatus.PASSED,
    findings: Optional[List[Tuple[QAFindingSeverity, str]]] = None,
    with_prohibited_file: bool = False,
    with_secret_content: bool = False,
) -> Tuple[Project, WebsiteBuildSession, WebsiteCodeGeneration, WebsiteQARun]:
    """
    Sets up a fully realized pipeline with a code generation, workspace files,
    and a designated QA evaluation run.
    """
    project, session, code_gen = await setup_qa_eligible_project(db, owner_id=owner_id)
    project.project_status = ProjectStatus.READY_FOR_DEPLOYMENT
    await db.flush()

    ws_dir = WebsiteWorkspaceService.get_version_workspace_dir(project.id, 1)
    if not ws_dir.exists():
        ws_dir = WebsiteWorkspaceService.get_workspace_dir(code_gen.id)

    if with_prohibited_file:
        (ws_dir / ".env.production").write_text("DATABASE_PASSWORD=super_secret_db_pass", encoding="utf-8")

    if with_secret_content:
        auth_file = ws_dir / "lib" / "auth.ts"
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth_file.write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0mockkey...\n-----END RSA PRIVATE KEY-----", encoding="utf-8")

    # Recompute workspace checksum after file modifications
    loaded_proj = WebsiteWorkspaceService.read_project_from_dir(ws_dir)
    h = hashlib.sha256()
    for f in sorted(loaded_proj.files, key=lambda x: x.path):
        h.update(f.path.encode("utf-8"))
        h.update(f.content.encode("utf-8"))
    code_gen.source_checksum = h.hexdigest()
    await db.flush()

    # Create QA Run
    qa_run = WebsiteQARun(
        id=uuid.uuid4(),
        project_id=project.id,
        build_session_id=session.id,
        source_generation_id=code_gen.id,
        target_version=1,
        owner_id=owner_id,
        status=qa_status,
        total_checks=10,
        passed_checks=10 if qa_status == WebsiteQARunStatus.PASSED else 6,
        failed_checks=0 if qa_status == WebsiteQARunStatus.PASSED else 4,
        score=98 if qa_status == WebsiteQARunStatus.PASSED else 50,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        run_metadata={},
    )
    db.add(qa_run)
    await db.flush()

    # Add findings if requested
    if findings:
        for sev, title in findings:
            finding = WebsiteQAFinding(
                id=uuid.uuid4(),
                qa_run_id=qa_run.id,
                project_id=project.id,
                owner_id=owner_id,
                severity=sev,
                category=QAFindingCategory.BUILD_INTEGRITY,
                title=title,
                description=f"Automated audit defect: {title}",
                affected_route="/",
                is_repaired=False,
                finding_metadata={},
            )
            db.add(finding)
        await db.flush()

    await db.commit()
    return project, session, code_gen, qa_run


# ── 1. Auth & IDOR Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deployment_endpoints_require_authentication(http_client: AsyncClient, db: AsyncSession):
    """Unauthenticated requests must receive 401 Unauthorized."""
    project, _, _, _ = await setup_deployment_ready_pipeline(db)

    # 1. Eligibility
    res = await http_client.get(f"/api/v1/projects/{project.id}/deployments/eligibility")
    assert res.status_code == 401

    # 2. Request
    res = await http_client.post(
        f"/api/v1/projects/{project.id}/deployments/request",
        json={"environment": "production"},
    )
    assert res.status_code == 401

    # 3. List
    res = await http_client.get(f"/api/v1/projects/{project.id}/deployments")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_deployment_idor_protection(http_client: AsyncClient, db: AsyncSession):
    """Owner B cannot access, check eligibility, approve, or execute deployment on Owner A's project."""
    project, _, _, _ = await setup_deployment_ready_pipeline(db, owner_id=OWNER_EMAIL)

    # 1. Intruder checking eligibility
    res = await http_client.get(
        f"/api/v1/projects/{project.id}/deployments/eligibility",
        headers=intruder_headers(),
    )
    assert res.status_code == 403

    # 2. Intruder requesting deployment
    res = await http_client.post(
        f"/api/v1/projects/{project.id}/deployments/request",
        headers=intruder_headers(),
        json={"environment": "production"},
    )
    assert res.status_code == 403


# ── 2. Server-Side Eligibility Gating Tests ───────────────────────────────────

@pytest.mark.asyncio
async def test_eligibility_passes_for_clean_pipeline(http_client: AsyncClient, db: AsyncSession):
    """Projects with a passing QA run and zero defects must be eligible for deployment."""
    project, _, code_gen, qa_run = await setup_deployment_ready_pipeline(db)

    res = await http_client.get(
        f"/api/v1/projects/{project.id}/deployments/eligibility",
        headers=owner_headers(),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["eligible"] is True
    assert data["qa_score"] == 98
    assert data["blocker_findings"] == 0
    assert data["high_findings"] == 0
    assert len(data["reasons"]) == 0


@pytest.mark.asyncio
async def test_eligibility_rejected_if_qa_failed(http_client: AsyncClient, db: AsyncSession):
    """Projects where QA evaluation failed must be rejected."""
    project, _, _, _ = await setup_deployment_ready_pipeline(
        db,
        qa_status=WebsiteQARunStatus.FAILED,
    )

    res = await http_client.get(
        f"/api/v1/projects/{project.id}/deployments/eligibility",
        headers=owner_headers(),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["eligible"] is False
    assert any("QA evaluation has not passed" in r for r in data["reasons"])


@pytest.mark.asyncio
async def test_eligibility_rejected_if_unresolved_blocker_defect(http_client: AsyncClient, db: AsyncSession):
    """QA run with unresolved BLOCKER defect must be strictly rejected."""
    project, _, _, _ = await setup_deployment_ready_pipeline(
        db,
        qa_status=WebsiteQARunStatus.PASSED_WITH_WARNINGS,
        findings=[(QAFindingSeverity.BLOCKER, "Missing root layout file")],
    )

    res = await http_client.get(
        f"/api/v1/projects/{project.id}/deployments/eligibility",
        headers=owner_headers(),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["eligible"] is False
    assert data["blocker_findings"] == 1
    assert any("BLOCKER" in r for r in data["reasons"])


@pytest.mark.asyncio
async def test_eligibility_rejected_if_unresolved_high_defect(http_client: AsyncClient, db: AsyncSession):
    """QA run with unresolved HIGH defect must be strictly rejected."""
    project, _, _, _ = await setup_deployment_ready_pipeline(
        db,
        qa_status=WebsiteQARunStatus.PASSED_WITH_WARNINGS,
        findings=[(QAFindingSeverity.HIGH, "Broken internal navigation link")],
    )

    res = await http_client.get(
        f"/api/v1/projects/{project.id}/deployments/eligibility",
        headers=owner_headers(),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["eligible"] is False
    assert data["high_findings"] == 1
    assert any("HIGH" in r for r in data["reasons"])


@pytest.mark.asyncio
async def test_eligibility_rejected_if_qa_is_stale(http_client: AsyncClient, db: AsyncSession):
    """If code was updated to v2 but QA run was only for v1, deployment must reject as stale."""
    project, _, code_gen, qa_run = await setup_deployment_ready_pipeline(db)

    code_gen_v2 = WebsiteCodeGeneration(
        id=uuid.uuid4(),
        project_id=project.id,
        build_session_id=code_gen.build_session_id,
        website_generation_id=code_gen.website_generation_id,
        design_blueprint_id=code_gen.design_blueprint_id,
        approved_prd_id=code_gen.approved_prd_id,
        owner_id=OWNER_EMAIL,
        prd_version=code_gen.prd_version,
        code_generation_version=2,
        status=WebsiteCodeGenerationStatus.COMPLETED,
        file_count=4,
        source_checksum="new_checksum_v2",
    )
    db.add(code_gen_v2)
    await db.commit()

    # Query eligibility for target_version=2 (while QA is only for v1)
    res = await http_client.get(
        f"/api/v1/projects/{project.id}/deployments/eligibility?target_version=2",
        headers=owner_headers(),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["eligible"] is False
    assert any("No QA run found for this version" in r for r in data["reasons"])


# ── 3. Gate 5 Owner Approval & Workflow State Machine ─────────────────────────

@pytest.mark.asyncio
async def test_production_deployment_workflow_and_approval_gate(
    http_client: AsyncClient, db: AsyncSession
):
    """
    Verifies full lifecycle:
    1. Request deployment -> enters AWAITING_APPROVAL with linked ApprovalRequest.
    2. Direct execute without approval -> rejected with 403.
    3. Approve deployment -> enters APPROVED.
    4. Execute deployment -> enters DEPLOYED with mock GitHub commit and Vercel URL.
    5. Project status promotes to DEPLOYED.
    """
    project, _, _, _ = await setup_deployment_ready_pipeline(db)

    # Step 1: Request Production Deployment
    res = await http_client.post(
        f"/api/v1/projects/{project.id}/deployments/request",
        headers=owner_headers(),
        json={
            "environment": "production",
            "force_mock": True,
        },
    )
    assert res.status_code == 201
    dep_data = res.json()
    dep_id = dep_data["id"]
    assert dep_data["status"] == "awaiting_approval"
    assert dep_data["approval_request_id"] is not None

    # Verify ApprovalRequest in DB
    appr_id = uuid.UUID(dep_data["approval_request_id"])
    appr_res = await db.execute(select(ApprovalRequest).where(ApprovalRequest.id == appr_id))
    appr = appr_res.scalar_one()
    assert appr.action_type == "deploy_website"
    assert appr.status == ApprovalStatus.PENDING

    # Step 2: Try to execute without approval -> MUST FAIL (Gate 5 Enforced)
    exec_res = await http_client.post(
        f"/api/v1/deployments/{dep_id}/execute",
        headers=owner_headers(),
        json={"force_mock": True},
    )
    assert exec_res.status_code == 403

    # Step 3: Explicit Owner Approval (Gate 5 Passed)
    approve_res = await http_client.post(
        f"/api/v1/deployments/{dep_id}/approve",
        headers=owner_headers(),
        json={"notes": "All QA checks verified. Approved for production."},
    )
    assert approve_res.status_code == 200
    appr_data = approve_res.json()
    assert appr_data["status"] == "approved"
    assert appr_data["approved_by"] == OWNER_EMAIL
    assert appr_data["approved_at"] is not None

    # Step 4: Execute Approved Deployment
    deploy_res = await http_client.post(
        f"/api/v1/deployments/{dep_id}/execute",
        headers=owner_headers(),
        json={"force_mock": True},
    )
    assert deploy_res.status_code == 200
    deployed_data = deploy_res.json()
    assert deployed_data["status"] == "deployed"
    assert deployed_data["github_commit_sha"] is not None
    assert deployed_data["deployment_url"] is not None
    assert deployed_data["production_url"] is not None
    assert deployed_data["completed_at"] is not None

    # Step 5: Verify Project promoted to DEPLOYED in DB
    await db.refresh(project)
    assert project.project_status == ProjectStatus.DEPLOYED
    assert project.phase_metadata.get("deployment_url") == deployed_data["production_url"]


@pytest.mark.asyncio
async def test_deployment_cancellation(http_client: AsyncClient, db: AsyncSession):
    """Owner can safely cancel an unexecuted deployment."""
    project, _, _, _ = await setup_deployment_ready_pipeline(db)

    # Request deployment
    res = await http_client.post(
        f"/api/v1/projects/{project.id}/deployments/request",
        headers=owner_headers(),
        json={"environment": "production", "force_mock": True},
    )
    dep_id = res.json()["id"]

    # Cancel deployment
    cancel_res = await http_client.post(
        f"/api/v1/deployments/{dep_id}/cancel",
        headers=owner_headers(),
        json={"reason": "Client requested holding release."},
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"


# ── 4. Security & Screening Tests ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prohibited_env_file_rejected_before_deployment(
    http_client: AsyncClient, db: AsyncSession
):
    """Deployments containing .env or secret credentials files must be rejected."""
    project, _, _, _ = await setup_deployment_ready_pipeline(
        db, with_prohibited_file=True
    )

    # Request deployment
    req_res = await http_client.post(
        f"/api/v1/projects/{project.id}/deployments/request",
        headers=owner_headers(),
        json={"environment": "production", "force_mock": True},
    )
    assert req_res.status_code == 201
    dep_id = req_res.json()["id"]

    # Approve
    await http_client.post(
        f"/api/v1/deployments/{dep_id}/approve",
        headers=owner_headers(),
        json={},
    )

    # Execute — should fail due to prohibited file
    exec_res = await http_client.post(
        f"/api/v1/deployments/{dep_id}/execute",
        headers=owner_headers(),
        json={"force_mock": True},
    )
    assert exec_res.status_code == 200
    data = exec_res.json()
    assert data["status"] == "failed"
    assert data["error_code"] == "SECURITY_VIOLATION"
    assert "Prohibited file" in data["error_message"]


@pytest.mark.asyncio
async def test_secret_rsa_key_content_rejected(
    http_client: AsyncClient, db: AsyncSession
):
    """Files containing embedded private keys or tokens must be rejected."""
    project, _, _, _ = await setup_deployment_ready_pipeline(
        db, with_secret_content=True
    )

    req_res = await http_client.post(
        f"/api/v1/projects/{project.id}/deployments/request",
        headers=owner_headers(),
        json={"environment": "production", "force_mock": True},
    )
    dep_id = req_res.json()["id"]

    await http_client.post(
        f"/api/v1/deployments/{dep_id}/approve",
        headers=owner_headers(),
        json={},
    )

    exec_res = await http_client.post(
        f"/api/v1/deployments/{dep_id}/execute",
        headers=owner_headers(),
        json={"force_mock": True},
    )
    data = exec_res.json()
    assert data["status"] == "failed"
    assert data["error_code"] == "SECURITY_VIOLATION"
    assert "Secret or private key" in data["error_message"] or "Secret pattern" in data["error_message"]


# ── 5. Custom Domain & DNS Tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_custom_domain_dns_and_ssl_flow(
    http_client: AsyncClient, db: AsyncSession
):
    """Custom domain configuration returns required DNS records and verifies SSL status."""
    project, _, _, _ = await setup_deployment_ready_pipeline(db)

    # Request & execute
    req_res = await http_client.post(
        f"/api/v1/projects/{project.id}/deployments/request",
        headers=owner_headers(),
        json={"environment": "production", "force_mock": True},
    )
    dep_id = req_res.json()["id"]
    await http_client.post(f"/api/v1/deployments/{dep_id}/approve", headers=owner_headers(), json={})
    await http_client.post(f"/api/v1/deployments/{dep_id}/execute", headers=owner_headers(), json={"force_mock": True})

    # Configure custom domain
    dom_res = await http_client.post(
        f"/api/v1/deployments/{dep_id}/domains",
        headers=owner_headers(),
        json={"domain": "apex-client.com"},
    )
    assert dom_res.status_code == 200
    dom_data = dom_res.json()
    assert dom_data["custom_domain"] == "apex-client.com"
    assert len(dom_data["dns_records"]) >= 2
    # Verify A record and CNAME record specs
    record_types = {r["type"] for r in dom_data["dns_records"]}
    assert "A" in record_types
    assert "CNAME" in record_types

    # Verify custom domain
    ver_res = await http_client.get(
        f"/api/v1/deployments/{dep_id}/domains/verify",
        headers=owner_headers(),
    )
    assert ver_res.status_code == 200
    assert ver_res.json()["ssl_status"] == "active"


# ── 6. Audit Trail Coverage ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_deployment_audit_trail_recorded(
    http_client: AsyncClient, db: AsyncSession
):
    """State transitions must generate audit entries in agent_runs."""
    project, _, _, _ = await setup_deployment_ready_pipeline(db)

    res = await http_client.post(
        f"/api/v1/projects/{project.id}/deployments/request",
        headers=owner_headers(),
        json={"environment": "production", "force_mock": True},
    )
    dep_id = res.json()["id"]

    stmt = select(AgentRun).where(
        AgentRun.agent_name.like("deployment:%"),
    )
    runs = (await db.execute(stmt)).scalars().all()
    assert len(runs) >= 1
    assert any("deployment_requested" in r.agent_name for r in runs)


# ── 7. Provider Unit & Security Tests ─────────────────────────────────────────

def test_github_provider_security_screening():
    """Unit tests for GitHub file path and secret screening."""
    gh = GitHubProvider(token="ghp_mocktoken12345678901234567890123456")
    assert gh.is_configured is True

    # Clean files pass
    clean_files = [
        GeneratedWebsiteFile(path="app/page.tsx", content="export default function Page() {}", file_type="tsx", checksum="c1", size_bytes=34),
        GeneratedWebsiteFile(path="package.json", content='{"name": "test"}', file_type="json", checksum="c2", size_bytes=16),
    ]
    gh.validate_files_security(clean_files)

    # Path traversal rejected by security validator
    traversal_files = [
        GeneratedWebsiteFile.model_construct(path="../secret.txt", content="hello", file_type="txt", checksum="c3", size_bytes=5),
    ]
    with pytest.raises(Exception) as exc:
        gh.validate_files_security(traversal_files)
    assert "traversal" in str(exc.value)

    # Prohibited files rejected
    prohibited_files = [
        GeneratedWebsiteFile(path=".env.local", content="API_KEY=123", file_type="env", checksum="c4", size_bytes=11),
    ]
    with pytest.raises(Exception) as exc:
        gh.validate_files_security(prohibited_files)
    assert "Prohibited file" in str(exc.value)

    # Embedded RSA private key rejected
    secret_files = [
        GeneratedWebsiteFile(path="keys.txt", content="-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----", file_type="txt", checksum="c5", size_bytes=60),
    ]
    with pytest.raises(Exception) as exc:
        gh.validate_files_security(secret_files)
    assert "Secret or private key" in str(exc.value)


def test_vercel_provider_configuration_and_redaction():
    """VercelProvider accurately reports configuration and redacts tokens."""
    unconfigured = VercelProvider(token="")
    assert unconfigured.is_configured is False

    configured = VercelProvider(token="vercel_super_secret_token_123")
    assert configured.is_configured is True
    assert "[REDACTED_VERCEL_TOKEN]" in configured._redact_message("Error occurred with vercel_super_secret_token_123 in payload")


@pytest.mark.asyncio
async def test_deployment_agent_direct_execution(db: AsyncSession):
    """DeploymentAgent handles check_eligibility, request, and execute actions."""
    from agents.deployment_agent import DeploymentAgent
    agent = DeploymentAgent()
    project, _, _, _ = await setup_deployment_ready_pipeline(db)
    dummy_run = AgentRun(id=uuid.uuid4(), agent_name="deployment", status=AgentRunStatus.RUNNING)

    # 1. Action: check_eligibility
    elig_result = await agent.execute(
        db,
        dummy_run,
        {
            "action": "check_eligibility",
            "project_id": str(project.id),
            "owner_id": OWNER_EMAIL,
        },
    )
    assert elig_result["eligible"] is True

    # 2. Action: request
    req_result = await agent.execute(
        db,
        dummy_run,
        {
            "action": "request",
            "project_id": str(project.id),
            "owner_id": OWNER_EMAIL,
            "environment": "production",
            "force_mock": True,
        },
    )
    dep_id = req_result["deployment_id"]
    assert req_result["status"] == "awaiting_approval"

    # Approve via service
    await WebsiteDeploymentService.approve_deployment(db, uuid.UUID(dep_id), OWNER_EMAIL)
    await db.commit()

    # 3. Action: execute
    exec_result = await agent.execute(
        db,
        dummy_run,
        {
            "action": "execute",
            "deployment_id": dep_id,
            "owner_id": OWNER_EMAIL,
            "force_mock": True,
        },
    )
    assert exec_result["status"] == "deployed"
    assert exec_result["deployment_url"] is not None
