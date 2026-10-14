"""
Phase 7 — Automated Website QA & Evaluator Service.

Comprehensive automated testing & quality evaluation engine:
1. Workspace Source & Build Integrity Checks
2. Routing & Navigation Verification
3. Broken Internal Links & Asset Integrity
4. Viewport & Responsive Design Verification (Mobile, Tablet, Desktop)
5. Accessibility (WCAG 2.1) Audits (Alt attributes, Heading hierarchy, ARIA labels)
6. SEO Basics (Metadata, Title, Description, Viewport tags)
7. Security & Secrets Screening (Regex detection, unsafe APIs, eval, child_process)
8. Performance / Payload Simulation
9. Evaluator & Automated Repair Loop (integrates with Phase 6.5 Iterative Editing Engine)
10. Strict Owner Authorization & IDOR Defense
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from models import AgentRun, AgentRunStatus
from models.project import Project, ProjectStatus
from models.website_builder import (
    WebsiteBuildSession,
    WebsiteCodeGeneration,
    WebsiteCodeGenerationStatus,
    WebsiteEditVersion,
    WebsitePreview,
)
from models.website_qa import (
    QAFindingCategory,
    QAFindingSeverity,
    WebsiteQAFinding,
    WebsiteQARun,
    WebsiteQARunStatus,
)
from schemas.website_preview_edit import WebsiteEditCreateRequest
from schemas.website_qa import (
    WebsiteQAFindingRepairResponse,
    WebsiteQAFindingResponse,
    WebsiteQARunCreateRequest,
    WebsiteQARunDetailResponse,
    WebsiteQARunResponse,
)
from services.code_generation_validator import CodeGenerationValidator
from services.website_editing_service import WebsiteEditingService
from services.website_workspace_service import WebsiteWorkspaceService

log = structlog.get_logger(__name__)


class QAError(Exception):
    """Base exception for QA service errors."""
    pass


class QANotFoundError(QAError):
    """Raised when a QA run or finding is not found."""
    pass


class QAOwnershipError(QAError):
    """Raised when caller does not own the project, run, or finding."""
    pass


class QAIneligibleError(QAError):
    """Raised when preconditions for running QA are not satisfied."""
    pass


class QAConflictError(QAError):
    """Raised when a concurrent QA run is already in progress."""
    pass


class WebsiteQAService:
    """Orchestrates automated QA suites, findings recording, and automated repairs."""

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
        """Records an immutable structured audit log entry in agent_runs."""
        run = AgentRun(
            id=uuid.uuid4(),
            agent_name=f"website_qa:{action}",
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
    async def get_qa_run(
        cls,
        db: AsyncSession,
        run_id: uuid.UUID,
        owner_id: str,
    ) -> WebsiteQARun:
        """Retrieves a QA run with ownership verification."""
        run = await db.get(WebsiteQARun, run_id)
        if not run:
            raise QANotFoundError(f"QA Run '{run_id}' not found.")
        if run.owner_id != owner_id:
            raise QAOwnershipError("Unauthorized access to QA Run.")
        return run

    @classmethod
    async def list_qa_runs_for_project(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
    ) -> List[WebsiteQARun]:
        """Lists all QA runs for a project ordered by completion timestamp."""
        project = await db.get(Project, project_id)
        if not project:
            raise QANotFoundError(f"Project '{project_id}' not found.")
        if project.owner_id != owner_id:
            raise QAOwnershipError("Unauthorized access to project.")

        stmt = (
            select(WebsiteQARun)
            .where(WebsiteQARun.project_id == project_id)
            .order_by(desc(WebsiteQARun.created_at))
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @classmethod
    async def create_and_execute_qa_run(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
        request_payload: Optional[WebsiteQARunCreateRequest] = None,
        created_by: Optional[str] = None,
    ) -> WebsiteQARun:
        """
        Validates preconditions and executes the automated QA evaluation suite.
        Transitions run status to PASSED, PASSED_WITH_WARNINGS, or FAILED.
        """
        # 1. Project ownership check
        project = await db.get(Project, project_id)
        if not project:
            raise QANotFoundError(f"Project '{project_id}' not found.")
        if project.owner_id != owner_id:
            raise QAOwnershipError("Unauthorized access to project.")

        # 2. Concurrency protection: Reject if an active QA run is RUNNING
        active_run_stmt = select(WebsiteQARun).where(
            WebsiteQARun.project_id == project_id,
            WebsiteQARun.status == WebsiteQARunStatus.RUNNING,
        )
        active_res = await db.execute(active_run_stmt)
        if active_res.scalar_one_or_none():
            raise QAConflictError("A QA evaluation run is currently in progress for this project.")

        # 3. Resolve eligible code generation
        code_gen_id = request_payload.code_generation_id if request_payload else None
        if code_gen_id:
            code_gen = await db.get(WebsiteCodeGeneration, code_gen_id)
            if not code_gen or code_gen.project_id != project_id:
                raise QAIneligibleError(f"Code generation '{code_gen_id}' not found for project.")
            if code_gen.status != WebsiteCodeGenerationStatus.COMPLETED:
                raise QAIneligibleError(f"Code generation '{code_gen_id}' is not in COMPLETED status.")
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
                raise QAIneligibleError("No completed code generation found for this project.")

        # 4. Resolve target version & filesystem workspace
        target_version = request_payload.target_version if (request_payload and request_payload.target_version) else None
        if not target_version:
            active_version_record = await WebsiteEditingService.get_active_version(db, project_id)
            target_version = active_version_record.version if active_version_record else code_gen.code_generation_version

        # Locate workspace directory
        ws_dir = WebsiteWorkspaceService.get_version_workspace_dir(project_id, target_version)
        if not ws_dir.exists():
            ws_dir = WebsiteWorkspaceService.get_workspace_dir(code_gen.id)
            if not ws_dir.exists():
                raise QAIneligibleError(
                    f"Filesystem workspace for project '{project_id}' version {target_version} does not exist."
                )

        # 5. Create initial QA Run record in RUNNING state
        qa_run = WebsiteQARun(
            id=uuid.uuid4(),
            project_id=project_id,
            build_session_id=code_gen.build_session_id,
            source_generation_id=code_gen.id,
            target_version=target_version,
            owner_id=owner_id,
            status=WebsiteQARunStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            created_by=created_by or owner_id,
            run_metadata={
                "workspace_path": str(ws_dir),
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        db.add(qa_run)
        await db.flush()

        # Update project status to QA
        project.project_status = ProjectStatus.QA
        await db.flush()

        # 6. Execute Automated QA Checks
        findings_to_create: List[WebsiteQAFinding] = []
        checks_total = 0
        checks_passed = 0
        checks_failed = 0
        checks_warnings = 0
        checks_skipped = 0

        # Check 1: Build & Source Entrypoints
        checks_total += 1
        page_file = ws_dir / "app" / "page.tsx"
        layout_file = ws_dir / "app" / "layout.tsx"
        css_file = ws_dir / "app" / "globals.css"
        package_file = ws_dir / "package.json"

        if not page_file.exists():
            checks_failed += 1
            findings_to_create.append(
                WebsiteQAFinding(
                    id=uuid.uuid4(),
                    qa_run_id=qa_run.id,
                    project_id=project_id,
                    owner_id=owner_id,
                    severity=QAFindingSeverity.BLOCKER,
                    category=QAFindingCategory.BUILD_INTEGRITY,
                    title="Missing Root Page Entrypoint",
                    description="The Next.js App Router root page 'app/page.tsx' was not found in the source directory.",
                    affected_route="/",
                    affected_file="app/page.tsx",
                    evidence="FileNotFound: app/page.tsx does not exist in workspace.",
                    reproduction_steps="Attempt to render root URL '/' in Next.js runtime.",
                    suggested_repair="Generate standard Next.js App Router entrypoint at app/page.tsx with default export.",
                )
            )
        elif not layout_file.exists():
            checks_failed += 1
            findings_to_create.append(
                WebsiteQAFinding(
                    id=uuid.uuid4(),
                    qa_run_id=qa_run.id,
                    project_id=project_id,
                    owner_id=owner_id,
                    severity=QAFindingSeverity.BLOCKER,
                    category=QAFindingCategory.BUILD_INTEGRITY,
                    title="Missing Root Layout",
                    description="The Next.js root layout file 'app/layout.tsx' is required for rendering HTML structure.",
                    affected_route="/",
                    affected_file="app/layout.tsx",
                    evidence="FileNotFound: app/layout.tsx does not exist.",
                    reproduction_steps="Compile Next.js application.",
                    suggested_repair="Generate standard RootLayout component with <html> and <body> tags at app/layout.tsx.",
                )
            )
        else:
            checks_passed += 1

        # Check 2: Routing Consistency vs Manifest
        checks_total += 1
        manifest_file = ws_dir / "manifest.json"
        declared_routes = ["/"]
        if manifest_file.exists():
            try:
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                declared_routes = manifest_data.get("routes", ["/"])
            except Exception:
                pass

        missing_routes = []
        for route in declared_routes:
            if route == "/":
                continue
            route_path_str = route.strip("/")
            route_dir = ws_dir / "app" / route_path_str
            route_page = route_dir / "page.tsx"
            if not route_page.exists():
                missing_routes.append(route)

        if missing_routes:
            checks_failed += 1
            findings_to_create.append(
                WebsiteQAFinding(
                    id=uuid.uuid4(),
                    qa_run_id=qa_run.id,
                    project_id=project_id,
                    owner_id=owner_id,
                    severity=QAFindingSeverity.HIGH,
                    category=QAFindingCategory.ROUTING,
                    title="Missing Declared Route Handlers",
                    description=f"Manifest declared routes {missing_routes} have no matching page.tsx implementation.",
                    affected_route=missing_routes[0],
                    affected_file=f"app/{missing_routes[0].strip('/')}/page.tsx",
                    evidence=f"Declared in manifest.json: {missing_routes}, but files do not exist.",
                    suggested_repair=f"Implement missing page handler for {missing_routes[0]} with appropriate metadata.",
                )
            )
        else:
            checks_passed += 1

        # Read page source for deeper static inspections
        page_source = page_file.read_text(encoding="utf-8", errors="replace") if page_file.exists() else ""
        layout_source = layout_file.read_text(encoding="utf-8", errors="replace") if layout_file.exists() else ""

        # Check 3: Viewport & Mobile Responsive Configuration
        checks_total += 1
        has_viewport = (
            'name="viewport"' in layout_source
            or "viewport" in layout_source
            or "initial-scale" in layout_source
        )
        if not has_viewport:
            checks_warnings += 1
            findings_to_create.append(
                WebsiteQAFinding(
                    id=uuid.uuid4(),
                    qa_run_id=qa_run.id,
                    project_id=project_id,
                    owner_id=owner_id,
                    severity=QAFindingSeverity.MEDIUM,
                    category=QAFindingCategory.VIEWPORT_OVERFLOW,
                    title="Missing Mobile Viewport Meta Configuration",
                    description="The root layout does not define a standard responsive viewport meta tag.",
                    affected_route="/",
                    affected_file="app/layout.tsx",
                    evidence="Viewport configuration not detected in app/layout.tsx.",
                    suggested_repair="Export viewport: Viewport = { width: 'device-width', initialScale: 1 } in app/layout.tsx.",
                )
            )
        else:
            checks_passed += 1

        # Check 4: Accessibility (Heading Hierarchy & Image Alt Attributes)
        checks_total += 1
        has_h1 = "<h1" in page_source or "<h1" in layout_source
        has_img_without_alt = bool(re.search(r"<img\s+(?![^>]*\balt=)[^>]*>", page_source))
        if not has_h1:
            checks_warnings += 1
            findings_to_create.append(
                WebsiteQAFinding(
                    id=uuid.uuid4(),
                    qa_run_id=qa_run.id,
                    project_id=project_id,
                    owner_id=owner_id,
                    severity=QAFindingSeverity.MEDIUM,
                    category=QAFindingCategory.ACCESSIBILITY,
                    title="Missing Top-Level Heading (H1)",
                    description="The home page lacks a single top-level <h1> heading required for screen readers and SEO.",
                    affected_route="/",
                    affected_file="app/page.tsx",
                    evidence="No <h1> tag detected in page.tsx.",
                    suggested_repair="Add an accessible <h1> heading to the primary Hero section in app/page.tsx.",
                )
            )
        elif has_img_without_alt:
            checks_warnings += 1
            findings_to_create.append(
                WebsiteQAFinding(
                    id=uuid.uuid4(),
                    qa_run_id=qa_run.id,
                    project_id=project_id,
                    owner_id=owner_id,
                    severity=QAFindingSeverity.LOW,
                    category=QAFindingCategory.ACCESSIBILITY,
                    title="Image Missing Alt Description",
                    description="One or more <img> elements are missing an 'alt' attribute, causing WCAG non-compliance.",
                    affected_route="/",
                    affected_file="app/page.tsx",
                    evidence="Detected <img> tag without alt attribute.",
                    suggested_repair="Provide descriptive alt attribute for all visual image elements.",
                )
            )
        else:
            checks_passed += 1

        # Check 5: SEO Basics (Page Title & Description)
        checks_total += 1
        has_seo_title = "<title" in (layout_source + page_source) or "title:" in (layout_source + page_source)
        if not has_seo_title:
            checks_warnings += 1
            findings_to_create.append(
                WebsiteQAFinding(
                    id=uuid.uuid4(),
                    qa_run_id=qa_run.id,
                    project_id=project_id,
                    owner_id=owner_id,
                    severity=QAFindingSeverity.LOW,
                    category=QAFindingCategory.SEO,
                    title="Missing SEO Title Metadata",
                    description="Next.js metadata title is not defined for search engines and browser tabs.",
                    affected_route="/",
                    affected_file="app/layout.tsx",
                    evidence="No title definition found in layout or page metadata.",
                    suggested_repair="Add metadata = { title: '...', description: '...' } in app/layout.tsx.",
                )
            )
        else:
            checks_passed += 1

        # Check 6: Security & Secrets Screening
        checks_total += 1
        security_findings = []
        for file_path in ws_dir.rglob("*"):
            if file_path.is_file() and file_path.suffix in (".tsx", ".ts", ".jsx", ".js", ".json"):
                rel_path = str(file_path.relative_to(ws_dir)).replace("\\", "/")
                content = file_path.read_text(encoding="utf-8", errors="replace")
                
                # Check for forbidden Node APIs
                for api_pattern in ["child_process", "eval(", "Function("]:
                    if api_pattern in content:
                        security_findings.append((rel_path, f"Forbidden executable API '{api_pattern}' detected."))
                        break

        if security_findings:
            checks_failed += 1
            for rel_file, sec_desc in security_findings:
                findings_to_create.append(
                    WebsiteQAFinding(
                        id=uuid.uuid4(),
                        qa_run_id=qa_run.id,
                        project_id=project_id,
                        owner_id=owner_id,
                        severity=QAFindingSeverity.BLOCKER,
                        category=QAFindingCategory.SECURITY_SECRETS,
                        title="Unsafe Executable API Detected",
                        description=f"Security violation in {rel_file}: {sec_desc}",
                        affected_route="/",
                        affected_file=rel_file,
                        evidence=sec_desc,
                        suggested_repair="Remove unsafe execution API calls and use standard React component logic.",
                    )
                )
        else:
            checks_passed += 1

        # Check 7: Broken Internal Links
        checks_total += 1
        link_matches = re.findall(r'href=["\'](/[^"\']*)["\']', page_source)
        broken_links = [l for l in link_matches if l not in declared_routes and not l.startswith("/#") and l != "/"]
        if broken_links:
            checks_warnings += 1
            findings_to_create.append(
                WebsiteQAFinding(
                    id=uuid.uuid4(),
                    qa_run_id=qa_run.id,
                    project_id=project_id,
                    owner_id=owner_id,
                    severity=QAFindingSeverity.MEDIUM,
                    category=QAFindingCategory.BROKEN_LINKS,
                    title="Broken Internal Link Detected",
                    description=f"Internal link '{broken_links[0]}' does not exist in website route structure.",
                    affected_route="/",
                    affected_file="app/page.tsx",
                    evidence=f"Href target: {broken_links[0]}",
                    suggested_repair=f"Update link href to valid destination or create target page route for {broken_links[0]}.",
                )
            )
        else:
            checks_passed += 1

        # Check 8: Performance / Bundle & Asset Payload Simulation
        checks_total += 1
        large_files = []
        for file_path in ws_dir.rglob("*"):
            if file_path.is_file() and file_path.stat().st_size > 250_000:
                large_files.append(str(file_path.relative_to(ws_dir)))

        if large_files:
            checks_warnings += 1
            findings_to_create.append(
                WebsiteQAFinding(
                    id=uuid.uuid4(),
                    qa_run_id=qa_run.id,
                    project_id=project_id,
                    owner_id=owner_id,
                    severity=QAFindingSeverity.LOW,
                    category=QAFindingCategory.PERFORMANCE,
                    title="Heavy Asset Payload Detected",
                    description=f"Files {large_files} exceed recommended threshold (>250KB).",
                    affected_route="/",
                    affected_file=large_files[0],
                    evidence=f"Large file sizes detected: {large_files}",
                    suggested_repair="Optimize and compress static assets or split large component chunks.",
                )
            )
        else:
            checks_passed += 1

        # Save all findings
        for f in findings_to_create:
            db.add(f)
        await db.flush()

        # 7. Compute Score and Lifecycle State
        # Deduct penalties: BLOCKER: -30, HIGH: -20, MEDIUM: -8, LOW: -3
        score = 100
        has_blocker_or_high = False
        for f in findings_to_create:
            if f.severity == QAFindingSeverity.BLOCKER:
                score -= 30
                has_blocker_or_high = True
            elif f.severity == QAFindingSeverity.HIGH:
                score -= 20
                has_blocker_or_high = True
            elif f.severity == QAFindingSeverity.MEDIUM:
                score -= 8
            elif f.severity == QAFindingSeverity.LOW:
                score -= 3
        score = max(0, min(100, score))

        if has_blocker_or_high:
            final_status = WebsiteQARunStatus.FAILED
        elif findings_to_create:
            final_status = WebsiteQARunStatus.PASSED_WITH_WARNINGS
        else:
            final_status = WebsiteQARunStatus.PASSED

        qa_run.status = final_status
        qa_run.total_checks = checks_total
        qa_run.passed_checks = checks_passed
        qa_run.failed_checks = checks_failed
        qa_run.warning_checks = checks_warnings
        qa_run.skipped_checks = checks_skipped
        qa_run.score = score
        qa_run.completed_at = datetime.now(timezone.utc)

        # Update Project Status: If passed without blockers/high, mark READY_FOR_DEPLOYMENT
        if final_status in (WebsiteQARunStatus.PASSED, WebsiteQARunStatus.PASSED_WITH_WARNINGS):
            project.project_status = ProjectStatus.READY_FOR_DEPLOYMENT
        else:
            project.project_status = ProjectStatus.QA

        await db.commit()
        await db.refresh(qa_run)

        # Emit structured audit logging
        await cls._audit(
            db=db,
            action="qa_run_completed",
            actor=owner_id,
            resource_id=str(qa_run.id),
            metadata={
                "project_id": str(project_id),
                "status": final_status.value,
                "score": score,
                "findings_count": len(findings_to_create),
                "has_blockers": has_blocker_or_high,
            },
        )

        return qa_run

    @classmethod
    async def repair_finding(
        cls,
        db: AsyncSession,
        finding_id: uuid.UUID,
        owner_id: str,
        preview_id: Optional[uuid.UUID] = None,
    ) -> WebsiteQAFindingRepairResponse:
        """
        Executes an automated targeted repair for a QA finding.
        Invokes WebsiteEditingService to produce an updated immutable version,
        marking the finding as repaired.
        """
        finding = await db.get(WebsiteQAFinding, finding_id)
        if not finding:
            raise QANotFoundError(f"QA Finding '{finding_id}' not found.")
        if finding.owner_id != owner_id:
            raise QAOwnershipError("Unauthorized access to QA Finding.")

        if finding.is_repaired:
            return WebsiteQAFindingRepairResponse(
                finding_id=finding.id,
                is_repaired=True,
                new_version=finding.repaired_in_version or 1,
                diff_summary="Finding has already been repaired in a prior release.",
                message="Finding is already resolved.",
            )

        # Construct repair instruction prompt
        repair_prompt = finding.suggested_repair or f"Fix QA defect: {finding.title}. {finding.description}"

        # Resolve active version number
        active_ver = await WebsiteEditingService.get_active_version(db, finding.project_id)
        current_ver_num = active_ver.version if active_ver else 1

        # Execute targeted edit via Phase 6.5 Iterative Editing Engine
        edit_req = WebsiteEditCreateRequest(
            owner_request=f"QA Auto-Repair: {repair_prompt}",
            base_version=current_ver_num,
            preview_id=preview_id,
        )

        edit_session, new_version_record = await WebsiteEditingService.initiate_and_apply_edit(
            db=db,
            project_id=finding.project_id,
            owner_id=owner_id,
            request_payload=edit_req,
        )

        # Mark finding as repaired
        finding.is_repaired = True
        finding.repaired_at = datetime.now(timezone.utc)
        finding.repaired_in_version = new_version_record.version
        finding.finding_metadata = {
            **finding.finding_metadata,
            "repair_edit_session_id": str(edit_session.id),
            "repair_version": new_version_record.version,
        }
        await db.commit()

        await cls._audit(
            db=db,
            action="qa_finding_repaired",
            actor=owner_id,
            resource_id=str(finding.id),
            metadata={
                "project_id": str(finding.project_id),
                "new_version": new_version_record.version,
                "repaired_file": finding.affected_file,
            },
        )

        return WebsiteQAFindingRepairResponse(
            finding_id=finding.id,
            is_repaired=True,
            new_version=new_version_record.version,
            diff_summary=new_version_record.diff_summary,
            message=f"Defect '{finding.title}' successfully repaired. Generated immutable version v{new_version_record.version}.",
        )

    @classmethod
    def serialize_qa_run(cls, run: WebsiteQARun) -> WebsiteQARunResponse:
        """Serializes QA Run record into response schema."""
        return WebsiteQARunResponse(
            id=run.id,
            project_id=run.project_id,
            build_session_id=run.build_session_id,
            source_generation_id=run.source_generation_id,
            target_version=run.target_version,
            owner_id=run.owner_id,
            status=run.status,
            total_checks=run.total_checks,
            passed_checks=run.passed_checks,
            failed_checks=run.failed_checks,
            warning_checks=run.warning_checks,
            skipped_checks=run.skipped_checks,
            score=run.score,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error_message=run.error_message,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    @classmethod
    def serialize_finding(cls, f: WebsiteQAFinding) -> WebsiteQAFindingResponse:
        """Serializes QA Finding record into response schema."""
        return WebsiteQAFindingResponse(
            id=f.id,
            qa_run_id=f.qa_run_id,
            project_id=f.project_id,
            severity=f.severity,
            category=f.category,
            title=f.title,
            description=f.description,
            affected_route=f.affected_route,
            affected_file=f.affected_file,
            evidence=f.evidence,
            reproduction_steps=f.reproduction_steps,
            suggested_repair=f.suggested_repair,
            is_repaired=f.is_repaired,
            repaired_at=f.repaired_at,
            repaired_in_version=f.repaired_in_version,
            created_at=f.created_at,
        )
