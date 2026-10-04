"""
Phase 6 Stage 6.4 — AI Website Code Generation Service.

Responsibilities:
1. Enforces strict input contracts (owner auth, project READY_FOR_BUILD, session READY/IN_PROGRESS,
   completed Generation & Blueprint, matching PRD version, Gate 4 validation, concurrency protection).
2. Manages sequential monotonic code generation versioning.
3. Coordinates CodeGenerationProvider execution with isolated prompt defense.
4. Executes deterministic CodeGenerationValidator checks (static safety, secrets, Next.js entrypoints).
5. Writes isolated disk workspace via WebsiteWorkspaceService and computes SHA-256 digests.
6. Stores immutable WEBSITE_SOURCE_CODE artifact in WebsiteBuildArtifact.
7. Emits structured, immutable audit log events via AgentRun.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from models import AgentRun, AgentRunStatus
from models.client_intelligence import ClientPRD, ClientRequirement, PRDStatus
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
from schemas.code_generation import (
    GeneratedWebsiteFile,
    GeneratedWebsiteProject,
    WebsiteCodeGenerationDetailResponse,
)
from schemas.design_blueprint import WebsiteDesignBlueprint
from schemas.website_specification import WebsiteSpecification
from services.code_generation_provider import (
    CodeGenerationProvider,
    get_code_generation_provider,
)
from services.code_generation_validator import (
    CodeGenerationValidator,
    CodeValidationError,
)
from services.website_workspace_service import WebsiteWorkspaceService

log = structlog.get_logger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class CodeGenerationError(Exception):
    """Base exception for code generation operations."""
    pass


class CodeGenerationNotFoundError(CodeGenerationError):
    """Raised when code generation or related record is not found."""
    pass


class CodeGenerationOwnershipError(CodeGenerationError):
    """Raised when owner isolation check fails (IDOR protection)."""
    pass


class CodeGenerationEligibilityError(CodeGenerationError):
    """Raised when preconditions for code generation are not met."""
    pass


class CodeGenerationPRDMismatchError(CodeGenerationError):
    """Raised when PRD version mismatch is detected."""
    pass


class CodeGenerationValidationFailureError(CodeGenerationError):
    """Raised when generated code fails static safety or structural validation."""
    pass


class CodeGenerationFailedError(CodeGenerationError):
    """Raised when code generation execution fails."""
    pass


# ── Service Implementation ───────────────────────────────────────────────────

class WebsiteCodeGenerationService:
    """Coordinates AI website code generation, deterministic validation, and artifact storage."""

    @staticmethod
    async def _audit(
        db: AsyncSession,
        event_name: str,
        status: AgentRunStatus,
        owner_id: str,
        details: Dict[str, Any],
        result: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Emits an immutable structured audit log entry to agent_runs."""
        run = AgentRun(
            id=uuid.uuid4(),
            agent_name=f"website_code_generation:{event_name}",
            status=status,
            input_data={"owner_id": owner_id, **details},
            output_data={"result": result} if result else None,
            error_message=error_message,
            tokens_used=0,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(run)
        await db.flush()

    @classmethod
    async def generate_code(
        cls,
        db: AsyncSession,
        session_id: uuid.UUID,
        owner_id: str,
        blueprint_id: Optional[uuid.UUID] = None,
        provider: Optional[CodeGenerationProvider] = None,
    ) -> WebsiteCodeGeneration:
        """
        Executes Next.js source code generation from a completed DesignBlueprint.
        """
        owner_id_clean = owner_id.lower().strip()

        # 1. Retrieve Build Session & verify ownership
        stmt_session = (
            select(WebsiteBuildSession)
            .where(WebsiteBuildSession.id == session_id)
            .options(selectinload(WebsiteBuildSession.project))
        )
        res_session = await db.execute(stmt_session)
        session = res_session.scalar_one_or_none()

        if not session:
            await cls._audit(
                db=db,
                event_name="code_generation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"session_id": str(session_id), "reason": "session_not_found"},
                error_message="WebsiteBuildSession not found",
            )
            await db.commit()
            raise CodeGenerationNotFoundError(f"WebsiteBuildSession '{session_id}' not found.")

        if session.owner_id.lower().strip() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="code_generation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"session_id": str(session_id), "reason": "idor_ownership_violation"},
                error_message="Unauthorized ownership mismatch",
            )
            await db.commit()
            raise CodeGenerationOwnershipError("You do not have access to this build session.")

        # 2. Check Build Session status (must be READY or IN_PROGRESS)
        if session.status not in (WebsiteBuildSessionStatus.READY, WebsiteBuildSessionStatus.IN_PROGRESS):
            await cls._audit(
                db=db,
                event_name="code_generation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"session_id": str(session_id), "session_status": session.status.value},
                error_message=f"Session status '{session.status.value}' is not eligible for code generation.",
            )
            await db.commit()
            raise CodeGenerationEligibilityError(
                f"Build session is in '{session.status.value}' status. Must be READY or IN_PROGRESS."
            )

        # 3. Retrieve Project & verify status
        stmt_proj = select(Project).where(Project.id == session.project_id)
        res_proj = await db.execute(stmt_proj)
        project = res_proj.scalar_one_or_none()

        if not project or project.owner_id.lower().strip() != owner_id_clean:
            raise CodeGenerationOwnershipError("Associated project ownership validation failed.")

        if project.project_status != ProjectStatus.READY_FOR_BUILD:
            raise CodeGenerationEligibilityError(
                f"Project is in '{project.project_status.value}' status. Must be READY_FOR_BUILD."
            )

        # 4. Check for active code generations (concurrency protection)
        stmt_active = select(WebsiteCodeGeneration).where(
            WebsiteCodeGeneration.build_session_id == session.id,
            WebsiteCodeGeneration.status.in_([
                WebsiteCodeGenerationStatus.PENDING,
                WebsiteCodeGenerationStatus.GENERATING,
                WebsiteCodeGenerationStatus.VALIDATING,
            ]),
        )
        res_active = await db.execute(stmt_active)
        if res_active.scalars().first():
            await cls._audit(
                db=db,
                event_name="code_generation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"session_id": str(session.id), "reason": "concurrent_generation_active"},
                error_message="A code generation is already active for this build session.",
            )
            await db.commit()
            raise CodeGenerationEligibilityError("A code generation is currently in progress for this build session.")

        # 5. Resolve Design Blueprint
        if blueprint_id:
            stmt_bp = select(DesignBlueprint).where(
                DesignBlueprint.id == blueprint_id,
                DesignBlueprint.build_session_id == session.id,
            )
        else:
            stmt_bp = (
                select(DesignBlueprint)
                .where(
                    DesignBlueprint.build_session_id == session.id,
                    DesignBlueprint.status == DesignBlueprintStatus.COMPLETED,
                )
                .order_by(desc(DesignBlueprint.blueprint_version))
            )
        res_bp = await db.execute(stmt_bp)
        blueprint_record = res_bp.scalars().first()

        if not blueprint_record:
            raise CodeGenerationNotFoundError("No completed DesignBlueprint found for this build session.")

        if blueprint_record.status != DesignBlueprintStatus.COMPLETED:
            raise CodeGenerationEligibilityError(
                f"Design Blueprint is in '{blueprint_record.status.value}' status. Must be COMPLETED."
            )

        # 6. Retrieve Source Generation and verify
        stmt_gen = select(WebsiteGeneration).where(WebsiteGeneration.id == blueprint_record.source_generation_id)
        res_gen = await db.execute(stmt_gen)
        generation_record = res_gen.scalar_one_or_none()

        if not generation_record or generation_record.status != WebsiteGenerationStatus.COMPLETED:
            raise CodeGenerationEligibilityError("Associated WebsiteGeneration is not COMPLETED.")

        if generation_record.build_session_id != session.id:
            raise CodeGenerationEligibilityError("WebsiteGeneration and DesignBlueprint session mismatch.")

        # 7. Check Gate 4 Approved PRD
        stmt_prd = select(ClientPRD).where(ClientPRD.id == project.approved_prd_id)
        res_prd = await db.execute(stmt_prd)
        prd = res_prd.scalar_one_or_none()

        if not prd or prd.status != PRDStatus.APPROVED:
            raise CodeGenerationEligibilityError("Gate 4 Approved PRD is missing or not in APPROVED status.")

        if prd.version != project.prd_version:
            raise CodeGenerationPRDMismatchError(
                f"PRD version mismatch: Project requires v{project.prd_version} but PRD is v{prd.version}."
            )

        # 8. Load WebsiteSpecification and WebsiteDesignBlueprint from artifacts
        stmt_spec_art = select(WebsiteBuildArtifact).where(
            WebsiteBuildArtifact.id == generation_record.specification_artifact_id
        )
        res_spec_art = await db.execute(stmt_spec_art)
        spec_artifact = res_spec_art.scalar_one_or_none()
        if not spec_artifact:
            raise CodeGenerationEligibilityError("WebsiteSpecification artifact not found.")

        specification = WebsiteSpecification.model_validate(spec_artifact.artifact_metadata)

        stmt_bp_art = select(WebsiteBuildArtifact).where(
            WebsiteBuildArtifact.id == blueprint_record.specification_artifact_id
        )
        res_bp_art = await db.execute(stmt_bp_art)
        bp_artifact = res_bp_art.scalar_one_or_none()
        if not bp_artifact:
            raise CodeGenerationEligibilityError("DesignBlueprint artifact not found.")

        blueprint_obj = WebsiteDesignBlueprint.model_validate(bp_artifact.artifact_metadata)

        # 9. Determine Monotonic Version
        stmt_ver = select(func.coalesce(func.max(WebsiteCodeGeneration.code_generation_version), 0)).where(
            WebsiteCodeGeneration.build_session_id == session.id
        )
        res_ver = await db.execute(stmt_ver)
        latest_version = res_ver.scalar_one()
        code_gen_version = latest_version + 1

        # 10. Instantiate Provider
        active_provider = provider or get_code_generation_provider()

        # 11. Create WebsiteCodeGeneration Row in PENDING status
        code_gen = WebsiteCodeGeneration(
            id=uuid.uuid4(),
            project_id=project.id,
            build_session_id=session.id,
            website_generation_id=generation_record.id,
            design_blueprint_id=blueprint_record.id,
            approved_prd_id=prd.id,
            owner_id=owner_id_clean,
            prd_version=project.prd_version,
            code_generation_version=code_gen_version,
            status=WebsiteCodeGenerationStatus.PENDING,
            provider=active_provider.provider_name,
            model=active_provider.model_name,
            file_count=0,
            generation_metadata={
                "project_name": project.project_name,
                "project_slug": project.project_slug,
                "blueprint_version": blueprint_record.blueprint_version,
                "generation_version": generation_record.generation_version,
            },
        )
        db.add(code_gen)
        await db.commit()
        await db.refresh(code_gen)

        await cls._audit(
            db=db,
            event_name="code_generation_requested",
            status=AgentRunStatus.PENDING,
            owner_id=owner_id_clean,
            details={
                "code_generation_id": str(code_gen.id),
                "version": code_gen_version,
                "session_id": str(session.id),
            },
            result="requested",
        )

        try:
            # 12. Transition to GENERATING
            code_gen.status = WebsiteCodeGenerationStatus.GENERATING
            code_gen.started_at = datetime.now(timezone.utc)
            await db.commit()

            await cls._audit(
                db=db,
                event_name="code_generation_started",
                status=AgentRunStatus.RUNNING,
                owner_id=owner_id_clean,
                details={
                    "code_generation_id": str(code_gen.id),
                    "provider": active_provider.provider_name,
                    "model": active_provider.model_name,
                },
                result="generating",
            )

            # Retrieve confirmed requirements
            stmt_reqs = select(ClientRequirement).where(
                ClientRequirement.conversation_id == prd.conversation_id
            )
            res_reqs = await db.execute(stmt_reqs)
            reqs = [
                {"title": r.title, "description": r.description, "category": r.category}
                for r in res_reqs.scalars().all()
            ]

            prd_dict = {
                "title": prd.title,
                "executive_summary": prd.executive_summary,
                "goals": prd.goals,
                "sitemap": prd.sitemap,
            }

            # 13. Call Provider to Generate Code
            project_code, provider_meta = await active_provider.generate_code(
                prd_data=prd_dict,
                specification=specification,
                blueprint=blueprint_obj,
                requirements=reqs,
                allowed_content={"company_name": project.project_name},
                context={
                    "code_generation_id": str(code_gen.id),
                    "code_generation_version": code_gen_version,
                },
            )

            # 14. Transition to VALIDATING
            code_gen.status = WebsiteCodeGenerationStatus.VALIDATING
            await db.commit()

            # Execute Deterministic Static Code Validation
            CodeGenerationValidator.validate_project(project_code)

            await cls._audit(
                db=db,
                event_name="code_generation_validated",
                status=AgentRunStatus.RUNNING,
                owner_id=owner_id_clean,
                details={
                    "code_generation_id": str(code_gen.id),
                    "file_count": len(project_code.files),
                    "routes_count": len(project_code.routes),
                },
                result="validated",
            )

            # 15. Write Isolated Filesystem Workspace & Compute Checksums
            ws_dir, source_checksum, manifest_files = WebsiteWorkspaceService.write_project_files(
                generation_id=code_gen.id,
                project=project_code,
            )

            # 16. Store WEBSITE_SOURCE_CODE Artifact
            project_dict = project_code.model_dump()
            artifact = WebsiteBuildArtifact(
                id=uuid.uuid4(),
                build_session_id=session.id,
                project_id=project.id,
                artifact_type=WebsiteBuildArtifactType.WEBSITE_SOURCE_CODE,
                artifact_name=f"website_source_code_v{code_gen_version}.json",
                artifact_version=code_gen_version,
                content_reference=f"code-generations/{code_gen.id}/workspace",
                artifact_metadata={
                    "framework": project_code.framework,
                    "language": project_code.language,
                    "source_checksum": source_checksum,
                    "file_count": len(project_code.files),
                    "entrypoints": project_code.entrypoints,
                    "routes": project_code.routes,
                    "components": project_code.components,
                    "files": manifest_files,
                    "full_source": project_dict,
                },
            )
            db.add(artifact)
            await db.flush()

            # 17. Complete Code Generation
            code_gen.status = WebsiteCodeGenerationStatus.COMPLETED
            code_gen.completed_at = datetime.now(timezone.utc)
            code_gen.source_checksum = source_checksum
            code_gen.file_count = len(project_code.files)
            code_gen.source_artifact_id = artifact.id
            code_gen.generation_metadata = {
                **code_gen.generation_metadata,
                **provider_meta,
                "framework": project_code.framework,
                "language": project_code.language,
                "routes": project_code.routes,
                "components": project_code.components,
                "workspace_path": str(ws_dir),
            }

            # Update session status to IN_PROGRESS if it was READY
            if session.status in (WebsiteBuildSessionStatus.READY, "ready"):
                session.status = WebsiteBuildSessionStatus.IN_PROGRESS

            await db.commit()
            await db.refresh(code_gen)

            await cls._audit(
                db=db,
                event_name="code_generation_completed",
                status=AgentRunStatus.COMPLETED,
                owner_id=owner_id_clean,
                details={
                    "code_generation_id": str(code_gen.id),
                    "version": code_gen_version,
                    "checksum": source_checksum,
                    "file_count": code_gen.file_count,
                    "artifact_id": str(artifact.id),
                },
                result="success",
            )

            return code_gen

        except Exception as exc:
            code_gen.status = WebsiteCodeGenerationStatus.FAILED
            code_gen.failed_at = datetime.now(timezone.utc)
            code_gen.error_code = exc.__class__.__name__
            code_gen.error_message = str(exc)
            await db.commit()

            # Clean up failed workspace
            WebsiteWorkspaceService.cleanup_workspace(code_gen.id)

            await cls._audit(
                db=db,
                event_name="code_generation_failed",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={
                    "code_generation_id": str(code_gen.id),
                    "error_code": code_gen.error_code,
                    "error_message": code_gen.error_message,
                },
                result="failed",
            )

            log.error("code_generation_failed", generation_id=str(code_gen.id), error=str(exc))
            if isinstance(exc, CodeValidationError):
                raise CodeGenerationValidationFailureError(f"Code validation failed: {exc}") from exc
            raise CodeGenerationFailedError(f"Website code generation failed: {exc}") from exc

    @classmethod
    async def cancel_code_generation(
        cls,
        db: AsyncSession,
        generation_id: uuid.UUID,
        owner_id: str,
        reason: Optional[str] = None,
    ) -> WebsiteCodeGeneration:
        """Cancels a pending, generating, or validating code generation."""
        owner_id_clean = owner_id.lower().strip()

        stmt = select(WebsiteCodeGeneration).where(WebsiteCodeGeneration.id == generation_id)
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()

        if not record:
            raise CodeGenerationNotFoundError(f"WebsiteCodeGeneration '{generation_id}' not found.")

        if record.owner_id.lower().strip() != owner_id_clean:
            raise CodeGenerationOwnershipError("Unauthorized access to code generation.")

        if record.status in (
            WebsiteCodeGenerationStatus.COMPLETED,
            WebsiteCodeGenerationStatus.FAILED,
            WebsiteCodeGenerationStatus.CANCELLED,
        ):
            raise CodeGenerationEligibilityError(
                f"Cannot cancel code generation in terminal '{record.status.value}' state."
            )

        record.status = WebsiteCodeGenerationStatus.CANCELLED
        record.failed_at = datetime.now(timezone.utc)
        record.error_code = "CancelledByUser"
        record.error_message = reason or "Cancelled by user"
        await db.commit()
        await db.refresh(record)

        WebsiteWorkspaceService.cleanup_workspace(record.id)

        await cls._audit(
            db=db,
            event_name="code_generation_cancelled",
            status=AgentRunStatus.CANCELLED,
            owner_id=owner_id_clean,
            details={"code_generation_id": str(record.id), "reason": record.error_message},
            result="cancelled",
        )

        return record

    @classmethod
    async def get_code_generation(
        cls,
        db: AsyncSession,
        generation_id: uuid.UUID,
        owner_id: str,
    ) -> Tuple[WebsiteCodeGeneration, Optional[Dict[str, Any]]]:
        """Retrieves details and manifest for a code generation."""
        owner_id_clean = owner_id.lower().strip()

        stmt = (
            select(WebsiteCodeGeneration)
            .where(WebsiteCodeGeneration.id == generation_id)
            .options(selectinload(WebsiteCodeGeneration.project))
        )
        res = await db.execute(stmt)
        record = res.scalar_one_or_none()

        if not record:
            raise CodeGenerationNotFoundError(f"WebsiteCodeGeneration '{generation_id}' not found.")

        if record.owner_id.lower().strip() != owner_id_clean:
            raise CodeGenerationOwnershipError("Unauthorized access to code generation.")

        manifest: Optional[Dict[str, Any]] = None
        if record.source_artifact_id:
            stmt_art = select(WebsiteBuildArtifact).where(WebsiteBuildArtifact.id == record.source_artifact_id)
            res_art = await db.execute(stmt_art)
            artifact = res_art.scalar_one_or_none()
            if artifact:
                manifest = {
                    "framework": artifact.artifact_metadata.get("framework", "nextjs"),
                    "language": artifact.artifact_metadata.get("language", "typescript"),
                    "source_checksum": artifact.artifact_metadata.get("source_checksum"),
                    "file_count": artifact.artifact_metadata.get("file_count", 0),
                    "entrypoints": artifact.artifact_metadata.get("entrypoints", []),
                    "routes": artifact.artifact_metadata.get("routes", []),
                    "components": artifact.artifact_metadata.get("components", []),
                    "files": artifact.artifact_metadata.get("files", []),
                }

        return record, manifest

    @classmethod
    async def list_code_generations(
        cls,
        db: AsyncSession,
        session_id: uuid.UUID,
        owner_id: str,
    ) -> List[WebsiteCodeGeneration]:
        """Lists code generations for a build session ordered by version descending."""
        owner_id_clean = owner_id.lower().strip()

        stmt_session = select(WebsiteBuildSession).where(WebsiteBuildSession.id == session_id)
        res_session = await db.execute(stmt_session)
        session = res_session.scalar_one_or_none()

        if not session:
            raise CodeGenerationNotFoundError(f"WebsiteBuildSession '{session_id}' not found.")

        if session.owner_id.lower().strip() != owner_id_clean:
            raise CodeGenerationOwnershipError("Unauthorized access to build session.")

        stmt = (
            select(WebsiteCodeGeneration)
            .where(WebsiteCodeGeneration.build_session_id == session_id)
            .order_by(desc(WebsiteCodeGeneration.code_generation_version))
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @classmethod
    async def get_code_generation_files(
        cls,
        db: AsyncSession,
        generation_id: uuid.UUID,
        owner_id: str,
        path: Optional[str] = None,
    ) -> List[GeneratedWebsiteFile]:
        """Retrieves generated files or a specific file for a code generation."""
        record, _ = await cls.get_code_generation(db, generation_id, owner_id)

        if not record.source_artifact_id:
            return []

        stmt_art = select(WebsiteBuildArtifact).where(WebsiteBuildArtifact.id == record.source_artifact_id)
        res_art = await db.execute(stmt_art)
        artifact = res_art.scalar_one_or_none()

        if not artifact:
            return []

        full_source = artifact.artifact_metadata.get("full_source", {})
        raw_files = full_source.get("files", [])

        file_objs = [GeneratedWebsiteFile.model_validate(f) for f in raw_files]

        if path:
            clean_path = path.strip().replace("\\", "/").lstrip("/")
            return [f for f in file_objs if f.path == clean_path]

        return file_objs
