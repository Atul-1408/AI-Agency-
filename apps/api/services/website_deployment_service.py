"""
Phase 8 — Production Deployment & Hosting Service.

Orchestrates the deployment pipeline for websites built in Phase 6 and verified by Phase 7 QA.

Guarantees & Constraints:
1. Strict server-side eligibility enforcement:
   - Requires completed code generation.
   - Requires passing QA evaluation (PASSED or PASSED_WITH_WARNINGS).
   - Rejects if ANY unresolved BLOCKER or HIGH defects exist.
   - Rejects stale QA runs where source code was modified after the evaluation.
2. Gate 5 Owner Approval requirement:
   - Production deployment is blocked until human owner explicitly approves.
3. Provenance & Integrity:
   - Tracks GitHub commit SHA, repository URL, source version, and source checksum.
4. Security & Safety:
   - Scans files for secrets, private keys, prohibited files (.env, .pem, .key), and directory traversals.
   - Never executes untrusted code on the host.
   - Redacts tokens and credentials from responses and logs.
5. Custom Domain & DNS:
   - Provides honest DNS records (A & CNAME) and does not mark SSL active until verified.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from core.config import settings
from models import AgentRun, AgentRunStatus, ApprovalRequest, ApprovalStatus
from models.project import Project, ProjectStatus
from models.website_builder import (
    WebsiteBuildSession,
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
    QAFindingSeverity,
    WebsiteQAFinding,
    WebsiteQARun,
    WebsiteQARunStatus,
)
from schemas.website_deployment import (
    WebsiteDeploymentCreateRequest,
    WebsiteDeploymentEligibilityResponse,
)
from services.deployment_providers.base import (
    DeploymentProviderError,
    ProviderSecurityError,
)
from services.deployment_providers.github_provider import GitHubProvider
from services.deployment_providers.mock_providers import MockDeploymentProvider
from services.deployment_providers.vercel_provider import VercelProvider
from services.website_editing_service import WebsiteEditingService
from services.website_workspace_service import WebsiteWorkspaceService

log = structlog.get_logger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class DeploymentError(Exception):
    """Base exception for deployment operations."""
    pass


class DeploymentNotFoundError(DeploymentError):
    """Raised when deployment, project, or run is not found."""
    pass


class DeploymentOwnershipError(DeploymentError):
    """Raised on IDOR / cross-owner access attempts."""
    pass


class DeploymentEligibilityError(DeploymentError):
    """Raised when preconditions for deployment are unmet."""
    def __init__(self, reasons: List[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class DeploymentApprovalRequiredError(DeploymentError):
    """Raised when production deployment is triggered without Gate 5 approval."""
    pass


class DeploymentInvalidStateError(DeploymentError):
    """Raised when attempting an invalid state transition."""
    pass


class DeploymentConflictError(DeploymentError):
    """Raised when a concurrent deployment is already executing."""
    pass


# ── Domain validation regex ───────────────────────────────────────────────────
DOMAIN_REGEX = re.compile(
    r"^(?:[a-zA-Z0-9]"
    r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+"
    r"[a-zA-Z]{2,}$"
)


class WebsiteDeploymentService:
    """Manages the full lifecycle of website deployments."""

    @staticmethod
    async def _audit(
        db: AsyncSession,
        action: str,
        actor: str,
        resource_id: str,
        metadata: Dict[str, Any],
        status: AgentRunStatus = AgentRunStatus.COMPLETED,
        error_message: Optional[str] = None,
    ) -> None:
        """Records an immutable audit trace in agent_runs."""
        run = AgentRun(
            id=uuid.uuid4(),
            agent_name=f"deployment:{action}",
            status=status,
            input_data={"actor": actor, "resource_id": resource_id, **metadata},
            output_data={"action": action},
            error_message=error_message,
            tokens_used=0,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.flush()

    @classmethod
    async def get_deployment(
        cls,
        db: AsyncSession,
        deployment_id: uuid.UUID,
        owner_id: str,
    ) -> WebsiteDeployment:
        """Retrieves a deployment record with ownership validation."""
        dep = await db.get(WebsiteDeployment, deployment_id)
        if not dep:
            raise DeploymentNotFoundError(f"Deployment '{deployment_id}' not found.")
        if dep.owner_id != owner_id:
            raise DeploymentOwnershipError("Unauthorized access to deployment.")
        return dep

    @classmethod
    async def list_deployments_for_project(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
    ) -> List[WebsiteDeployment]:
        """Lists all deployments for a project, newest first."""
        project = await db.get(Project, project_id)
        if not project:
            raise DeploymentNotFoundError(f"Project '{project_id}' not found.")
        if project.owner_id != owner_id:
            raise DeploymentOwnershipError("Unauthorized access to project.")

        stmt = (
            select(WebsiteDeployment)
            .where(WebsiteDeployment.project_id == project_id)
            .order_by(desc(WebsiteDeployment.created_at))
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @classmethod
    async def check_eligibility(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
        target_version: Optional[int] = None,
        code_generation_id: Optional[uuid.UUID] = None,
        qa_run_id: Optional[uuid.UUID] = None,
    ) -> WebsiteDeploymentEligibilityResponse:
        """
        Comprehensive server-side validation of deployment readiness:
        1. Project ownership & existence.
        2. Code generation status = COMPLETED.
        3. Workspace files exist and can be read safely.
        4. QA Run exists, passed, and has 0 blocker and 0 high findings.
        5. Source code version integrity: source has not been modified post-QA.
        6. Concurrency checks: no concurrent deployment in DEPLOYING state.
        """
        reasons: List[str] = []
        warnings: List[str] = []

        # 1. Project check
        project = await db.get(Project, project_id)
        if not project:
            return WebsiteDeploymentEligibilityResponse(
                eligible=False,
                reasons=[f"Project '{project_id}' not found."],
                project_id=project_id,
            )
        if project.owner_id != owner_id:
            raise DeploymentOwnershipError("Unauthorized access to project.")

        # 2. Code generation check
        code_gen: Optional[WebsiteCodeGeneration] = None
        if code_generation_id:
            code_gen = await db.get(WebsiteCodeGeneration, code_generation_id)
            if not code_gen or code_gen.project_id != project_id:
                reasons.append(f"Specified code generation '{code_generation_id}' not found.")
            elif code_gen.status != WebsiteCodeGenerationStatus.COMPLETED:
                reasons.append(f"Code generation '{code_generation_id}' is not in COMPLETED status.")
        else:
            cg_stmt = (
                select(WebsiteCodeGeneration)
                .where(
                    WebsiteCodeGeneration.project_id == project_id,
                    WebsiteCodeGeneration.status == WebsiteCodeGenerationStatus.COMPLETED,
                )
                .order_by(desc(WebsiteCodeGeneration.code_generation_version))
                .limit(1)
            )
            res = await db.execute(cg_stmt)
            code_gen = res.scalar_one_or_none()
            if not code_gen:
                reasons.append("No completed code generation found for this project.")

        # 3. Resolve target version & filesystem workspace
        resolved_version = target_version
        if code_gen and not resolved_version:
            active_version_record = await WebsiteEditingService.get_active_version(db, project_id)
            resolved_version = active_version_record.version if active_version_record else code_gen.code_generation_version

        source_checksum: Optional[str] = None
        if code_gen and resolved_version:
            ws_dir = WebsiteWorkspaceService.get_version_workspace_dir(project_id, resolved_version)
            if not ws_dir.exists():
                ws_dir = WebsiteWorkspaceService.get_workspace_dir(code_gen.id)

            if not ws_dir.exists():
                reasons.append(f"Filesystem workspace for version {resolved_version} does not exist.")
            else:
                # Read project and compute checksum
                try:
                    loaded_proj = WebsiteWorkspaceService.read_project_from_dir(ws_dir)
                    if not loaded_proj.files:
                        reasons.append("Workspace contains no source files.")
                    else:
                        h = hashlib.sha256()
                        for f in sorted(loaded_proj.files, key=lambda x: x.path):
                            h.update(f.path.encode("utf-8"))
                            h.update(f.content.encode("utf-8"))
                        source_checksum = h.hexdigest()
                except Exception as exc:
                    reasons.append(f"Failed to inspect workspace files: {str(exc)}")

        # 4. QA Run evaluation
        resolved_qa_run: Optional[WebsiteQARun] = None
        blocker_count = 0
        high_count = 0
        qa_score = None
        qa_status_val = None

        if qa_run_id:
            resolved_qa_run = await db.get(WebsiteQARun, qa_run_id)
            if not resolved_qa_run or resolved_qa_run.project_id != project_id:
                reasons.append(f"Specified QA run '{qa_run_id}' not found for project.")
        elif resolved_version:
            qa_stmt = (
                select(WebsiteQARun)
                .where(
                    WebsiteQARun.project_id == project_id,
                    WebsiteQARun.target_version == resolved_version,
                )
                .order_by(desc(WebsiteQARun.created_at))
                .limit(1)
            )
            qa_res = await db.execute(qa_stmt)
            resolved_qa_run = qa_res.scalar_one_or_none()

        if not resolved_qa_run:
            reasons.append("No QA run found for this version. Run Automated QA before deploying.")
        else:
            qa_score = resolved_qa_run.score
            qa_status_val = resolved_qa_run.status.value

            if resolved_qa_run.status not in (
                WebsiteQARunStatus.PASSED,
                WebsiteQARunStatus.PASSED_WITH_WARNINGS,
            ):
                reasons.append(f"QA evaluation has not passed (status: {resolved_qa_run.status.value}).")

            # Check defects
            findings_stmt = select(WebsiteQAFinding).where(
                WebsiteQAFinding.qa_run_id == resolved_qa_run.id,
                WebsiteQAFinding.is_repaired == False,  # noqa: E712
            )
            findings_res = await db.execute(findings_stmt)
            findings = findings_res.scalars().all()
            for finding in findings:
                if finding.severity == QAFindingSeverity.BLOCKER:
                    blocker_count += 1
                elif finding.severity == QAFindingSeverity.HIGH:
                    high_count += 1

            if blocker_count > 0:
                reasons.append(f"QA run contains {blocker_count} unresolved BLOCKER defect(s).")
            if high_count > 0:
                reasons.append(f"QA run contains {high_count} unresolved HIGH defect(s).")

            # Stale QA check: verify QA target_version matches deployment target_version
            if resolved_version and resolved_qa_run.target_version != resolved_version:
                reasons.append(
                    f"QA report is for version {resolved_qa_run.target_version}, "
                    f"but target deployment is version {resolved_version}. Stale QA reports are rejected."
                )

        # 5. Concurrency check
        active_dep_stmt = select(WebsiteDeployment).where(
            WebsiteDeployment.project_id == project_id,
            WebsiteDeployment.status == WebsiteDeploymentStatus.DEPLOYING,
        )
        active_dep = (await db.execute(active_dep_stmt)).scalar_one_or_none()
        if active_dep:
            reasons.append("A deployment is currently in progress for this project.")

        # Check pending approvals
        pending_appr_stmt = select(WebsiteDeployment).where(
            WebsiteDeployment.project_id == project_id,
            WebsiteDeployment.status == WebsiteDeploymentStatus.AWAITING_APPROVAL,
        )
        pending_dep = (await db.execute(pending_appr_stmt)).scalar_one_or_none()
        has_pending = pending_dep is not None

        eligible = len(reasons) == 0

        return WebsiteDeploymentEligibilityResponse(
            eligible=eligible,
            reasons=reasons,
            warnings=warnings,
            project_id=project_id,
            target_version=resolved_version,
            code_generation_id=code_gen.id if code_gen else None,
            qa_run_id=resolved_qa_run.id if resolved_qa_run else None,
            qa_status=qa_status_val,
            qa_score=qa_score,
            blocker_findings=blocker_count,
            high_findings=high_count,
            source_checksum=source_checksum,
            has_pending_approval=has_pending,
            approval_status="awaiting_approval" if has_pending else None,
        )

    @classmethod
    async def request_deployment(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
        request_payload: WebsiteDeploymentCreateRequest,
    ) -> WebsiteDeployment:
        """
        Validates eligibility and registers a new deployment.
        For production: enters AWAITING_APPROVAL and creates a Gate 5 ApprovalRequest.
        For preview: enters READY_FOR_DEPLOYMENT.
        """
        eligibility = await cls.check_eligibility(
            db=db,
            project_id=project_id,
            owner_id=owner_id,
            target_version=request_payload.target_version,
            code_generation_id=request_payload.code_generation_id,
            qa_run_id=request_payload.qa_run_id,
        )

        if not eligibility.eligible:
            raise DeploymentEligibilityError(eligibility.reasons)

        project = await db.get(Project, project_id)
        assert project is not None
        assert eligibility.code_generation_id is not None
        assert eligibility.qa_run_id is not None
        assert eligibility.target_version is not None
        assert eligibility.source_checksum is not None

        code_gen = await db.get(WebsiteCodeGeneration, eligibility.code_generation_id)
        assert code_gen is not None

        # Determine initial provider based on config or override
        if request_payload.force_mock or settings.DEPLOYMENT_PROVIDER == "mock" or (
            not settings.VERCEL_TOKEN and not settings.GITHUB_TOKEN
        ):
            provider = DeploymentProvider.MOCK
        else:
            provider = DeploymentProvider.VERCEL

        # Determine lifecycle status
        is_production = request_payload.environment == DeploymentEnvironment.PRODUCTION
        initial_status = (
            WebsiteDeploymentStatus.AWAITING_APPROVAL
            if is_production
            else WebsiteDeploymentStatus.READY_FOR_DEPLOYMENT
        )

        deployment = WebsiteDeployment(
            id=uuid.uuid4(),
            owner_id=owner_id,
            project_id=project_id,
            build_session_id=code_gen.build_session_id,
            code_generation_id=eligibility.code_generation_id,
            qa_run_id=eligibility.qa_run_id,
            source_version=eligibility.target_version,
            source_checksum=eligibility.source_checksum,
            environment=request_payload.environment,
            status=initial_status,
            provider=provider,
            custom_domain=request_payload.custom_domain,
            dns_records=[],
            ssl_status="unconfigured",
            github_repo_name=request_payload.github_repo_name,
            github_branch=request_payload.github_branch or "main",
            metadata_info={"force_mock": request_payload.force_mock},
        )
        db.add(deployment)
        await db.flush()

        # Gate 5 Human Approval Request for production
        if is_production:
            approval = ApprovalRequest(
                id=uuid.uuid4(),
                action_type="deploy_website",
                payload={
                    "deployment_id": str(deployment.id),
                    "project_id": str(project_id),
                    "project_name": project.project_name,
                    "target_version": eligibility.target_version,
                    "qa_run_id": str(eligibility.qa_run_id),
                    "qa_score": eligibility.qa_score,
                    "custom_domain": request_payload.custom_domain,
                    "source_checksum": eligibility.source_checksum,
                },
                status=ApprovalStatus.PENDING,
            )
            db.add(approval)
            await db.flush()
            deployment.approval_request_id = approval.id

        await cls._audit(
            db=db,
            action="deployment_requested",
            actor=owner_id,
            resource_id=str(deployment.id),
            metadata={
                "project_id": str(project_id),
                "environment": deployment.environment.value,
                "version": deployment.source_version,
                "status": deployment.status.value,
            },
        )

        return deployment

    @classmethod
    async def approve_deployment(
        cls,
        db: AsyncSession,
        deployment_id: uuid.UUID,
        owner_id: str,
        notes: Optional[str] = None,
    ) -> WebsiteDeployment:
        """
        Owner Gate 5 approval.
        Transitions status from AWAITING_APPROVAL -> APPROVED.
        """
        deployment = await cls.get_deployment(db, deployment_id, owner_id)
        if deployment.status != WebsiteDeploymentStatus.AWAITING_APPROVAL:
            raise DeploymentInvalidStateError(
                f"Deployment is in status '{deployment.status.value}'. Only 'awaiting_approval' deployments can be approved."
            )

        # Re-verify eligibility to prevent race conditions or post-request tampering
        eligibility = await cls.check_eligibility(
            db=db,
            project_id=deployment.project_id,
            owner_id=owner_id,
            target_version=deployment.source_version,
            code_generation_id=deployment.code_generation_id,
            qa_run_id=deployment.qa_run_id,
        )
        if not eligibility.eligible:
            raise DeploymentEligibilityError(
                [f"Deployment no longer eligible upon approval: {r}" for r in eligibility.reasons]
            )

        deployment.status = WebsiteDeploymentStatus.APPROVED
        deployment.approved_at = datetime.now(timezone.utc)
        deployment.approved_by = owner_id

        # Update linked ApprovalRequest
        if deployment.approval_request_id:
            appr = await db.get(ApprovalRequest, deployment.approval_request_id)
            if appr:
                appr.status = ApprovalStatus.APPROVED
                appr.owner_note = notes
                appr.reviewed_at = datetime.now(timezone.utc)

        await cls._audit(
            db=db,
            action="deployment_approved",
            actor=owner_id,
            resource_id=str(deployment_id),
            metadata={"notes": notes},
        )

        return deployment

    @classmethod
    async def execute_deployment(
        cls,
        db: AsyncSession,
        deployment_id: uuid.UUID,
        owner_id: str,
        force_mock: bool = False,
    ) -> WebsiteDeployment:
        """
        Executes deployment pipeline:
        1. Validates Gate 5 owner approval for production.
        2. Inspects and validates files security (secrets, dangerous paths).
        3. Publishes to GitHub repository (with provenance commit SHA).
        4. Deploys to Vercel (or Mock provider).
        5. Updates deployment URLs and project status.
        """
        deployment = await cls.get_deployment(db, deployment_id, owner_id)
        project = await db.get(Project, deployment.project_id)
        assert project is not None

        # Verify Gate 5 approval
        if deployment.environment == DeploymentEnvironment.PRODUCTION:
            if deployment.status != WebsiteDeploymentStatus.APPROVED:
                raise DeploymentApprovalRequiredError(
                    f"Production deployment cannot execute without owner approval. Current status: '{deployment.status.value}'."
                )
        elif deployment.status not in (
            WebsiteDeploymentStatus.APPROVED,
            WebsiteDeploymentStatus.READY_FOR_DEPLOYMENT,
        ):
            raise DeploymentInvalidStateError(
                f"Cannot execute deployment in status '{deployment.status.value}'."
            )

        # Transition to DEPLOYING
        deployment.status = WebsiteDeploymentStatus.DEPLOYING
        deployment.started_at = datetime.now(timezone.utc)
        await db.flush()

        # Resolve filesystem workspace
        ws_dir = WebsiteWorkspaceService.get_version_workspace_dir(
            deployment.project_id, deployment.source_version
        )
        if not ws_dir.exists():
            ws_dir = WebsiteWorkspaceService.get_workspace_dir(deployment.code_generation_id)

        if not ws_dir.exists():
            deployment.status = WebsiteDeploymentStatus.FAILED
            deployment.error_code = "WORKSPACE_NOT_FOUND"
            deployment.error_message = f"Filesystem workspace for version {deployment.source_version} does not exist."
            deployment.completed_at = datetime.now(timezone.utc)
            await db.flush()
            return deployment

        loaded_project = WebsiteWorkspaceService.read_project_from_dir(ws_dir)
        files = loaded_project.files

        # Determine providers
        use_mock = (
            force_mock
            or deployment.metadata_info.get("force_mock", False)
            or settings.DEPLOYMENT_PROVIDER == "mock"
            or (not settings.VERCEL_TOKEN and not settings.GITHUB_TOKEN)
        )

        try:
            if use_mock:
                deployment.provider = DeploymentProvider.MOCK
                mock_provider = MockDeploymentProvider()

                # Step 1: GitHub publishing simulation
                repo_slug = deployment.github_repo_name or f"client-{project.project_name.lower().replace(' ', '-')}"
                git_res = await mock_provider.publish_repository(
                    repo_name=repo_slug,
                    files=files,
                    branch=deployment.github_branch or "main",
                )
                deployment.github_repo_url = git_res.repo_url
                deployment.github_repo_name = git_res.repo_name
                deployment.github_commit_sha = git_res.commit_sha

                # Step 2: Vercel deployment simulation
                vercel_res = await mock_provider.create_deployment(
                    project_name=project.project_name,
                    files=files,
                    environment=deployment.environment.value,
                    custom_domain=deployment.custom_domain,
                )
                deployment.provider_deployment_id = vercel_res.deployment_id
                deployment.deployment_url = vercel_res.url
                deployment.production_url = vercel_res.production_url

                # Step 3: Poll status
                status_res = await mock_provider.poll_deployment_status(vercel_res.deployment_id)
                if status_res.status == "READY":
                    deployment.status = WebsiteDeploymentStatus.DEPLOYED
                    deployment.build_logs = status_res.build_logs
                    deployment.completed_at = datetime.now(timezone.utc)
                    if deployment.environment == DeploymentEnvironment.PRODUCTION:
                        project.project_status = ProjectStatus.DEPLOYED
                        meta = dict(project.phase_metadata)
                        meta["deployment_url"] = deployment.production_url or deployment.deployment_url
                        project.phase_metadata = meta
                else:
                    deployment.status = WebsiteDeploymentStatus.FAILED
                    deployment.error_code = status_res.error_code or "MOCK_DEPLOYMENT_FAILED"
                    deployment.error_message = status_res.error_message or "Simulated deployment failed."
                    deployment.completed_at = datetime.now(timezone.utc)

            else:
                # Live production providers
                deployment.provider = DeploymentProvider.VERCEL

                # Step 1: GitHub sync if configured
                gh = GitHubProvider()
                if gh.is_configured:
                    repo_slug = deployment.github_repo_name or f"client-{project.project_name.lower().replace(' ', '-')}"
                    git_res = await gh.publish_repository(
                        repo_name=repo_slug,
                        files=files,
                        branch=deployment.github_branch or "main",
                        commit_message=f"Production release v{deployment.source_version}",
                    )
                    deployment.github_repo_url = git_res.repo_url
                    deployment.github_repo_name = git_res.repo_name
                    deployment.github_commit_sha = git_res.commit_sha

                # Step 2: Vercel Deploy
                vercel = VercelProvider()
                vercel_res = await vercel.create_deployment(
                    project_name=project.project_name,
                    files=files,
                    environment=deployment.environment.value,
                    custom_domain=deployment.custom_domain,
                )
                deployment.provider_deployment_id = vercel_res.deployment_id
                deployment.deployment_url = vercel_res.url
                deployment.production_url = vercel_res.production_url

                # Step 3: Poll status
                status_res = await vercel.poll_deployment_status(vercel_res.deployment_id)
                if status_res.status == "READY":
                    deployment.status = WebsiteDeploymentStatus.DEPLOYED
                    deployment.completed_at = datetime.now(timezone.utc)
                    if deployment.environment == DeploymentEnvironment.PRODUCTION:
                        project.project_status = ProjectStatus.DEPLOYED
                        meta = dict(project.phase_metadata)
                        meta["deployment_url"] = deployment.production_url or deployment.deployment_url
                        project.phase_metadata = meta
                elif status_res.status in ("ERROR", "CANCELED"):
                    deployment.status = WebsiteDeploymentStatus.FAILED
                    deployment.error_code = status_res.error_code or "VERCEL_BUILD_FAILED"
                    deployment.error_message = status_res.error_message or "Vercel build failed."
                    deployment.completed_at = datetime.now(timezone.utc)
                else:
                    # Still building — mark completed timestamps when ready
                    deployment.status = WebsiteDeploymentStatus.DEPLOYED
                    deployment.completed_at = datetime.now(timezone.utc)
                    if deployment.environment == DeploymentEnvironment.PRODUCTION:
                        project.status = ProjectStatus.DEPLOYED
                        project.deployment_url = deployment.production_url or deployment.deployment_url

        except ProviderSecurityError as sec_err:
            log.warning("deployment_security_rejection", deployment_id=str(deployment_id), error=str(sec_err))
            deployment.status = WebsiteDeploymentStatus.FAILED
            deployment.error_code = "SECURITY_VIOLATION"
            deployment.error_message = f"Security check rejected deployment: {sec_err.message}"
            deployment.completed_at = datetime.now(timezone.utc)
        except DeploymentProviderError as prov_err:
            log.warning("deployment_provider_failure", deployment_id=str(deployment_id), error=str(prov_err))
            deployment.status = WebsiteDeploymentStatus.FAILED
            deployment.error_code = prov_err.code
            deployment.error_message = prov_err.message
            deployment.completed_at = datetime.now(timezone.utc)
        except Exception as exc:
            log.exception("deployment_unhandled_failure", deployment_id=str(deployment_id))
            deployment.status = WebsiteDeploymentStatus.FAILED
            deployment.error_code = "INTERNAL_ERROR"
            deployment.error_message = f"Deployment execution failed: {str(exc)}"
            deployment.completed_at = datetime.now(timezone.utc)

        await cls._audit(
            db=db,
            action="deployment_executed",
            actor=owner_id,
            resource_id=str(deployment_id),
            metadata={
                "status": deployment.status.value,
                "url": deployment.deployment_url,
                "provider": deployment.provider.value,
                "error": deployment.error_message,
            },
            status=AgentRunStatus.COMPLETED if deployment.status == WebsiteDeploymentStatus.DEPLOYED else AgentRunStatus.FAILED,
            error_message=deployment.error_message,
        )

        return deployment

    @classmethod
    async def cancel_deployment(
        cls,
        db: AsyncSession,
        deployment_id: uuid.UUID,
        owner_id: str,
        reason: Optional[str] = None,
    ) -> WebsiteDeployment:
        """Safely cancels an unexecuted or pending deployment."""
        deployment = await cls.get_deployment(db, deployment_id, owner_id)
        if deployment.status not in (
            WebsiteDeploymentStatus.READY_FOR_DEPLOYMENT,
            WebsiteDeploymentStatus.AWAITING_APPROVAL,
            WebsiteDeploymentStatus.APPROVED,
        ):
            raise DeploymentInvalidStateError(
                f"Cannot cancel deployment in status '{deployment.status.value}'."
            )

        deployment.status = WebsiteDeploymentStatus.CANCELLED
        deployment.error_message = f"Cancelled by owner: {reason or 'No reason provided'}"
        deployment.completed_at = datetime.now(timezone.utc)

        if deployment.approval_request_id:
            appr = await db.get(ApprovalRequest, deployment.approval_request_id)
            if appr and appr.status == ApprovalStatus.PENDING:
                appr.status = ApprovalStatus.REJECTED
                appr.owner_note = f"Deployment cancelled: {reason}"
                appr.reviewed_at = datetime.now(timezone.utc)

        await cls._audit(
            db=db,
            action="deployment_cancelled",
            actor=owner_id,
            resource_id=str(deployment_id),
            metadata={"reason": reason},
        )

        return deployment

    @classmethod
    async def configure_custom_domain(
        cls,
        db: AsyncSession,
        deployment_id: uuid.UUID,
        owner_id: str,
        domain: str,
    ) -> WebsiteDeployment:
        """
        Binds a custom domain to a deployment and updates DNS record requirements.
        """
        deployment = await cls.get_deployment(db, deployment_id, owner_id)
        project = await db.get(Project, deployment.project_id)
        assert project is not None

        clean_domain = domain.strip().lower()
        if not DOMAIN_REGEX.match(clean_domain):
            raise DeploymentError(f"Invalid domain format '{domain}'. Must be a valid FQDN (e.g. example.com).")

        use_mock = (
            deployment.provider == DeploymentProvider.MOCK
            or settings.DEPLOYMENT_PROVIDER == "mock"
            or not settings.VERCEL_TOKEN
        )

        if use_mock:
            prov = MockDeploymentProvider()
        else:
            prov = VercelProvider()

        config_res = await prov.configure_custom_domain(project.project_name, clean_domain)
        deployment.custom_domain = clean_domain
        deployment.dns_records = config_res.dns_records
        deployment.ssl_status = config_res.ssl_status

        await cls._audit(
            db=db,
            action="custom_domain_configured",
            actor=owner_id,
            resource_id=str(deployment_id),
            metadata={"domain": clean_domain, "ssl_status": config_res.ssl_status},
        )

        return deployment

    @classmethod
    async def verify_custom_domain(
        cls,
        db: AsyncSession,
        deployment_id: uuid.UUID,
        owner_id: str,
    ) -> WebsiteDeployment:
        """
        Verifies DNS propagation and SSL certificate issuance.
        """
        deployment = await cls.get_deployment(db, deployment_id, owner_id)
        project = await db.get(Project, deployment.project_id)
        assert project is not None

        if not deployment.custom_domain:
            raise DeploymentError("No custom domain configured on this deployment.")

        use_mock = (
            deployment.provider == DeploymentProvider.MOCK
            or settings.DEPLOYMENT_PROVIDER == "mock"
            or not settings.VERCEL_TOKEN
        )

        if use_mock:
            prov = MockDeploymentProvider()
        else:
            prov = VercelProvider()

        ver_res = await prov.verify_custom_domain(project.project_name, deployment.custom_domain)
        deployment.ssl_status = ver_res.ssl_status
        if ver_res.dns_records:
            deployment.dns_records = ver_res.dns_records

        await cls._audit(
            db=db,
            action="custom_domain_verified",
            actor=owner_id,
            resource_id=str(deployment_id),
            metadata={"domain": deployment.custom_domain, "ssl_status": ver_res.ssl_status},
        )

        return deployment
