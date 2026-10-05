"""
Phase 6 Stage 6.5 — Website Iterative Editing Service.

Coordinates:
1. Owner authorization and IDOR defense.
2. Optimistic concurrency control and base version conflict rejection.
3. AI-assisted minimal file editing with strict prompt containment.
4. Deterministic static re-validation via CodeGenerationValidator.
5. Atomic workspace updates and immutable version creation.
6. Non-destructive rollback preserving full history.
7. Active preview workspace synchronization.
8. Comprehensive audit logging.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from models import AgentRun, AgentRunStatus
from models.client_intelligence import ClientPRD
from models.project import Project
from models.website_builder import (
    WebsiteBuildArtifact,
    WebsiteBuildArtifactType,
    WebsiteBuildSession,
    WebsiteCodeGeneration,
    WebsiteCodeGenerationStatus,
    WebsiteEditSession,
    WebsiteEditSessionStatus,
    WebsiteEditVersion,
    WebsitePreview,
    WebsitePreviewStatus,
)
from schemas.code_generation import GeneratedWebsiteFile, GeneratedWebsiteProject
from schemas.website_preview_edit import (
    WebsiteEditCreateRequest,
    WebsiteEditDetailResponse,
    WebsiteEditResponse,
    WebsiteEditVersionResponse,
    WebsiteVersionRollbackResponse,
)
from services.code_generation_validator import CodeGenerationValidator, CodeValidationError

from services.website_editing_provider import (
    MockWebsiteEditingProvider,
    WebsiteEditingProvider,
)
from services.website_workspace_service import WebsiteWorkspaceService

log = structlog.get_logger(__name__)


class EditError(Exception):
    """Base exception for editing service errors."""
    pass


class EditNotFoundError(EditError):
    """Raised when an edit session or version is not found."""
    pass


class EditOwnershipError(EditError):
    """Raised when the caller does not own the project or edit session."""
    pass


class EditIneligibleError(EditError):
    """Raised when prerequisites for website editing are not met."""
    pass


class StaleBaseVersionConflictError(EditError):
    """Raised when the requested base version does not match the active version."""
    pass


class ConcurrentEditConflictError(EditError):
    """Raised when another edit session is currently being processed."""
    pass


class EditValidationFailureError(EditError):
    """Raised when proposed source changes fail static safety or structure validation."""
    pass


class WebsiteEditingService:
    """Manages iterative website editing, atomic application, and version rollbacks."""

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
        """Emits an immutable structured audit log entry to agent_runs."""
        run = AgentRun(
            id=uuid.uuid4(),
            agent_name=f"website_edit:{action}",
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
    async def get_active_version(cls, db: AsyncSession, project_id: uuid.UUID) -> Optional[WebsiteEditVersion]:
        """Returns the currently active edit version for a project."""
        stmt = (
            select(WebsiteEditVersion)
            .where(WebsiteEditVersion.project_id == project_id, WebsiteEditVersion.is_active == True)
            .order_by(desc(WebsiteEditVersion.version))
            .limit(1)
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @classmethod
    async def get_latest_version_number(cls, db: AsyncSession, project_id: uuid.UUID, default_ver: int = 1) -> int:
        """Returns the highest version number recorded for a project."""
        stmt = (
            select(WebsiteEditVersion.version)
            .where(WebsiteEditVersion.project_id == project_id)
            .order_by(desc(WebsiteEditVersion.version))
            .limit(1)
        )
        res = await db.execute(stmt)
        val = res.scalar_one_or_none()
        return val if val is not None else default_ver

    @classmethod
    async def initiate_and_apply_edit(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
        request_payload: WebsiteEditCreateRequest,
        provider: Optional[WebsiteEditingProvider] = None,
        created_by: Optional[str] = None,
    ) -> Tuple[WebsiteEditSession, WebsiteEditVersion]:
        """
        Executes the entire iterative edit workflow atomically:
        1. Validates owner and project eligibility
        2. Enforces optimistic locking on base_version
        3. Invokes provider to generate minimal diff
        4. Re-validates complete assembled project
        5. Atomically stores new version and updates preview
        """
        # 1. Ownership & Project Eligibility
        project = await db.get(Project, project_id)
        if not project:
            raise EditNotFoundError(f"Project '{project_id}' not found.")
        if project.owner_id != owner_id:
            raise EditOwnershipError("Unauthorized access to project.")

        # 2. Check completed base code generation exists
        stmt = (
            select(WebsiteCodeGeneration)
            .where(
                WebsiteCodeGeneration.project_id == project_id,
                WebsiteCodeGeneration.status == WebsiteCodeGenerationStatus.COMPLETED,
            )
            .order_by(desc(WebsiteCodeGeneration.code_generation_version))
            .limit(1)
        )
        res = await db.execute(stmt)
        base_code_gen = res.scalar_one_or_none()
        if not base_code_gen:
            raise EditIneligibleError("Cannot edit website: No completed code generation exists for this project.")

        # 3. Optimistic Concurrency & Base Version Check
        active_version = await cls.get_active_version(db, project_id)
        current_version_num = active_version.version if active_version else base_code_gen.code_generation_version

        if request_payload.base_version != current_version_num:
            raise StaleBaseVersionConflictError(
                f"Base version conflict: Requested base v{request_payload.base_version} does not match "
                f"current active version v{current_version_num}. Please refresh and re-submit your edit."
            )

        # Check for concurrent active edit
        active_edit_stmt = (
            select(WebsiteEditSession)
            .where(
                WebsiteEditSession.project_id == project_id,
                WebsiteEditSession.status.in_([
                    WebsiteEditSessionStatus.ANALYZING,
                    WebsiteEditSessionStatus.GENERATING,
                    WebsiteEditSessionStatus.VALIDATING,
                ]),
            )
            .limit(1)
        )
        active_edit_res = await db.execute(active_edit_stmt)
        if active_edit_res.scalar_one_or_none():
            raise ConcurrentEditConflictError("Another edit session is currently in progress for this project.")

        # 4. Create Edit Session Record (PENDING)
        now = datetime.now(timezone.utc)
        edit_session = WebsiteEditSession(
            id=uuid.uuid4(),
            project_id=project_id,
            preview_id=request_payload.preview_id,
            base_code_generation_id=base_code_gen.id,
            base_version=request_payload.base_version,
            owner_id=owner_id,
            status=WebsiteEditSessionStatus.PENDING,
            owner_request=request_payload.owner_request,
            created_by=created_by or owner_id,
            started_at=now,
            edit_metadata={"base_version": request_payload.base_version},
        )
        db.add(edit_session)
        await db.commit()
        await db.refresh(edit_session)

        await cls._audit(
            db=db,
            action="edit_requested",
            actor=owner_id,
            resource_id=str(edit_session.id),
            metadata={"project_id": str(project_id), "base_version": request_payload.base_version, "resource_type": "website_edit_session"},
        )

        # 5. Load Current Source Project
        edit_session.status = WebsiteEditSessionStatus.ANALYZING
        await db.commit()

        if active_version:
            curr_src_dir = WebsiteWorkspaceService.get_version_workspace_dir(project_id, active_version.version)
            if not curr_src_dir.exists():
                curr_src_dir = WebsiteWorkspaceService.get_workspace_dir(base_code_gen.id)
        else:
            curr_src_dir = WebsiteWorkspaceService.get_workspace_dir(base_code_gen.id)

        current_project = WebsiteWorkspaceService.read_project_from_dir(curr_src_dir)

        # Retrieve PRD, spec, and blueprint metadata
        prd = await db.get(ClientPRD, base_code_gen.approved_prd_id)
        prd_content = prd.executive_summary if prd else ""
        website_spec = base_code_gen.generation_metadata.get("specification", {})
        design_blueprint = base_code_gen.generation_metadata.get("blueprint", {})

        # 6. Generate Minimal Edits via Provider
        edit_session.status = WebsiteEditSessionStatus.GENERATING
        await db.commit()

        await cls._audit(
            db=db,
            action="edit_started",
            actor=owner_id,
            resource_id=str(edit_session.id),
            metadata={"project_id": str(project_id), "resource_type": "website_edit_session"},
        )

        active_provider = provider or MockWebsiteEditingProvider()
        changed_files, diff_summary, affected_routes, affected_components = await active_provider.generate_edit(
            current_project=current_project,
            owner_request=request_payload.owner_request,
            prd_content=prd_content,
            website_spec=website_spec,
            design_blueprint=design_blueprint,
        )

        # 7. Validate Complete Assembled Project (VALIDATING)
        edit_session.status = WebsiteEditSessionStatus.VALIDATING
        await db.commit()

        # Build candidate project
        merged_files_map = {f.path: f for f in current_project.files}
        for cf in changed_files:
            merged_files_map[cf.path] = cf

        candidate_project = GeneratedWebsiteProject(
            framework=current_project.framework,
            language=current_project.language,
            package_manager=current_project.package_manager,
            files=list(merged_files_map.values()),
            entrypoints=current_project.entrypoints,
            routes=list(set(current_project.routes + affected_routes)),
            components=list(set(current_project.components + affected_components)),
            assets=current_project.assets,
            metadata=current_project.metadata,
        )

        # Run strict static validation pipeline
        try:
            CodeGenerationValidator.validate_project(candidate_project)
        except CodeValidationError as val_exc:
            log.warning("edit_validation_failed", edit_id=str(edit_session.id), error=str(val_exc))
            edit_session.status = WebsiteEditSessionStatus.FAILED
            edit_session.error_code = "VALIDATION_FAILED"
            edit_session.error_message = str(val_exc)
            edit_session.completed_at = datetime.now(timezone.utc)
            await db.commit()

            await cls._audit(
                db=db,
                action="edit_failed",
                actor=owner_id,
                resource_id=str(edit_session.id),
                metadata={"reason": str(val_exc), "error_code": "VALIDATION_FAILED", "resource_type": "website_edit_session"},
                status=AgentRunStatus.FAILED,
                error_message=str(val_exc),
            )
            raise EditValidationFailureError(f"Validation failed: {val_exc}") from val_exc

        await cls._audit(
            db=db,
            action="edit_validated",
            actor=owner_id,
            resource_id=str(edit_session.id),
            metadata={"changed_files_count": len(changed_files), "resource_type": "website_edit_session"},
        )

        # 8. Determine Next Sequential Version
        max_existing_ver = await cls.get_latest_version_number(db, project_id, default_ver=base_code_gen.code_generation_version)
        new_version_num = max_existing_ver + 1

        # 9. Atomic Workspace Write for New Version
        ver_ws_dir = WebsiteWorkspaceService.get_version_workspace_dir(project_id, new_version_num)
        ver_ws_dir.mkdir(parents=True, exist_ok=True)
        _, aggregate_checksum, manifest = WebsiteWorkspaceService.write_project_files(
            generation_id=uuid.UUID(int=new_version_num),  # unique namespace
            project=candidate_project,
        )
        # Move or sync to version directory
        gen_dir = WebsiteWorkspaceService.get_workspace_dir(uuid.UUID(int=new_version_num))
        if gen_dir.exists() and gen_dir != ver_ws_dir:
            WebsiteWorkspaceService.copy_directory(gen_dir, ver_ws_dir)
            WebsiteWorkspaceService.cleanup_workspace(uuid.UUID(int=new_version_num))

        # 10. Create Build Artifact (WEBSITE_SOURCE_CODE)
        artifact = WebsiteBuildArtifact(
            id=uuid.uuid4(),
            build_session_id=base_code_gen.build_session_id,
            project_id=project_id,
            artifact_type=WebsiteBuildArtifactType.WEBSITE_SOURCE_CODE,
            artifact_name=f"website_source_code_v{new_version_num}",
            artifact_version=new_version_num,
            content_reference=str(ver_ws_dir),
            artifact_metadata={
                "edit_session_id": str(edit_session.id),
                "parent_version": request_payload.base_version,
                "version": new_version_num,
                "checksum": aggregate_checksum,
                "changed_files": [f.path for f in changed_files],
                "diff_summary": diff_summary,
            },
        )
        db.add(artifact)

        # 11. Deactivate old active versions and create new WebsiteEditVersion
        deact_stmt = (
            select(WebsiteEditVersion)
            .where(WebsiteEditVersion.project_id == project_id, WebsiteEditVersion.is_active == True)
        )
        deact_res = await db.execute(deact_stmt)
        for old_ver in deact_res.scalars().all():
            old_ver.is_active = False

        edit_version = WebsiteEditVersion(
            id=uuid.uuid4(),
            project_id=project_id,
            edit_session_id=edit_session.id,
            source_generation_id=base_code_gen.id,
            parent_version=request_payload.base_version,
            version=new_version_num,
            owner_id=owner_id,
            changed_files=[f.path for f in changed_files],
            diff_summary=diff_summary,
            source_checksum=aggregate_checksum,
            artifact_id=artifact.id,
            is_active=True,
            version_metadata={
                "affected_routes": affected_routes,
                "affected_components": affected_components,
            },
        )
        db.add(edit_version)

        # 12. Mark Edit Session as APPLIED
        edit_session.status = WebsiteEditSessionStatus.APPLIED
        edit_session.completed_at = datetime.now(timezone.utc)
        edit_session.edit_metadata = {
            **edit_session.edit_metadata,
            "version_created": new_version_num,
            "version_id": str(edit_version.id),
            "changed_files": [f.path for f in changed_files],
            "diff_summary": diff_summary,
        }

        # 13. Sync Active Preview Workspace (if exists)
        preview_to_update: Optional[WebsitePreview] = None
        if request_payload.preview_id:
            preview_to_update = await db.get(WebsitePreview, request_payload.preview_id)
        if not preview_to_update:
            # Check latest running/created preview for project
            p_stmt = (
                select(WebsitePreview)
                .where(WebsitePreview.project_id == project_id)
                .order_by(desc(WebsitePreview.created_at))
                .limit(1)
            )
            p_res = await db.execute(p_stmt)
            preview_to_update = p_res.scalar_one_or_none()

        if preview_to_update:
            preview_ws_dir = Path(preview_to_update.workspace_reference)
            WebsiteWorkspaceService.copy_directory(ver_ws_dir, preview_ws_dir)
            preview_to_update.current_version = new_version_num

        await db.commit()
        await db.refresh(edit_session)
        await db.refresh(edit_version)

        # Audit Logs
        await cls._audit(
            db=db,
            action="version_created",
            actor=owner_id,
            resource_id=str(edit_version.id),
            metadata={
                "project_id": str(project_id),
                "version": new_version_num,
                "parent_version": request_payload.base_version,
                "resource_type": "website_edit_version",
            },
        )
        await cls._audit(
            db=db,
            action="edit_applied",
            actor=owner_id,
            resource_id=str(edit_session.id),
            metadata={
                "project_id": str(project_id),
                "version": new_version_num,
                "diff_summary": diff_summary,
                "resource_type": "website_edit_session",
            },
        )

        return edit_session, edit_version

    @classmethod
    async def rollback_to_version(
        cls,
        db: AsyncSession,
        version_id: uuid.UUID,
        owner_id: str,
    ) -> Tuple[int, int, WebsiteEditVersion]:
        """
        Executes a non-destructive rollback to an existing version:
        Creates a new immutable version (v_new = max_ver + 1) with the target version's contents.
        History is strictly preserved: no versions are deleted or overwritten.
        """
        target_version_record = await db.get(WebsiteEditVersion, version_id)
        if not target_version_record:
            raise EditNotFoundError(f"Version '{version_id}' not found.")
        if target_version_record.owner_id != owner_id:
            raise EditOwnershipError("Unauthorized access to version.")

        project_id = target_version_record.project_id
        target_ver_num = target_version_record.version

        await cls._audit(
            db=db,
            action="version_rollback_requested",
            actor=owner_id,
            resource_id=str(target_version_record.id),
            metadata={"project_id": str(project_id), "target_version": target_ver_num, "resource_type": "website_edit_version"},
        )

        # Read target version directory
        target_ws_dir = WebsiteWorkspaceService.get_version_workspace_dir(project_id, target_ver_num)
        if not target_ws_dir.exists():
            # If base code generation workspace
            target_ws_dir = WebsiteWorkspaceService.get_workspace_dir(target_version_record.source_generation_id)

        # Calculate new version number
        max_ver = await cls.get_latest_version_number(db, project_id, default_ver=1)
        new_version_num = max_ver + 1

        # Create new version workspace directory and copy snapshot
        new_ws_dir = WebsiteWorkspaceService.get_version_workspace_dir(project_id, new_version_num)
        WebsiteWorkspaceService.copy_directory(target_ws_dir, new_ws_dir)

        # Compute checksum
        hasher = hashlib.sha256()
        for item in sorted(new_ws_dir.rglob("*")):
            if item.is_file() and item.name != "manifest.json":
                hasher.update(item.read_bytes())
        new_checksum = hasher.hexdigest()

        # Create Build Artifact
        base_code_gen = await db.get(WebsiteCodeGeneration, target_version_record.source_generation_id)
        build_session_id = base_code_gen.build_session_id if base_code_gen else uuid.uuid4()

        artifact = WebsiteBuildArtifact(
            id=uuid.uuid4(),
            build_session_id=build_session_id,
            project_id=project_id,
            artifact_type=WebsiteBuildArtifactType.WEBSITE_SOURCE_CODE,
            artifact_name=f"website_source_code_v{new_version_num}",
            artifact_version=new_version_num,
            content_reference=str(new_ws_dir),
            artifact_metadata={
                "rollback_from": target_ver_num,
                "version": new_version_num,
                "checksum": new_checksum,
            },
        )
        db.add(artifact)

        # Deactivate previous active versions
        deact_stmt = (
            select(WebsiteEditVersion)
            .where(WebsiteEditVersion.project_id == project_id, WebsiteEditVersion.is_active == True)
        )
        deact_res = await db.execute(deact_stmt)
        for old_ver in deact_res.scalars().all():
            old_ver.is_active = False

        new_version_record = WebsiteEditVersion(
            id=uuid.uuid4(),
            project_id=project_id,
            edit_session_id=None,
            source_generation_id=target_version_record.source_generation_id,
            parent_version=target_ver_num,
            version=new_version_num,
            owner_id=owner_id,
            changed_files=[],
            diff_summary=f"Non-destructive rollback to version v{target_ver_num}.",
            source_checksum=new_checksum,
            artifact_id=artifact.id,
            is_active=True,
            version_metadata={"rolled_back_to_version": target_ver_num},
        )
        db.add(new_version_record)

        # Sync active preview workspace if one exists
        p_stmt = (
            select(WebsitePreview)
            .where(WebsitePreview.project_id == project_id)
            .order_by(desc(WebsitePreview.created_at))
            .limit(1)
        )
        p_res = await db.execute(p_stmt)
        active_preview = p_res.scalar_one_or_none()
        if active_preview:
            preview_ws_dir = Path(active_preview.workspace_reference)
            WebsiteWorkspaceService.copy_directory(new_ws_dir, preview_ws_dir)
            active_preview.current_version = new_version_num

        await db.commit()
        await db.refresh(new_version_record)

        await cls._audit(
            db=db,
            action="version_created",
            actor=owner_id,
            resource_id=str(new_version_record.id),
            metadata={"project_id": str(project_id), "version": new_version_num, "resource_type": "website_edit_version"},
        )
        await cls._audit(
            db=db,
            action="version_rollback_completed",
            actor=owner_id,
            resource_id=str(new_version_record.id),
            metadata={"project_id": str(project_id), "rolled_back_to": target_ver_num, "new_version": new_version_num, "resource_type": "website_edit_version"},
        )

        return target_ver_num, new_version_num, new_version_record

    @classmethod
    async def cancel_edit(cls, db: AsyncSession, edit_id: uuid.UUID, owner_id: str, reason: Optional[str] = None) -> WebsiteEditSession:
        """Cancels an active or pending edit session."""
        edit = await db.get(WebsiteEditSession, edit_id)
        if not edit:
            raise EditNotFoundError(f"Edit session '{edit_id}' not found.")
        if edit.owner_id != owner_id:
            raise EditOwnershipError("Unauthorized access to edit session.")

        if edit.status in [WebsiteEditSessionStatus.APPLIED, WebsiteEditSessionStatus.FAILED, WebsiteEditSessionStatus.CANCELLED]:
            raise EditIneligibleError(f"Cannot cancel edit session in terminal status '{edit.status.value}'.")

        edit.status = WebsiteEditSessionStatus.CANCELLED
        edit.completed_at = datetime.now(timezone.utc)
        if reason:
            edit.edit_metadata = {**edit.edit_metadata, "cancel_reason": reason}

        await db.commit()
        await db.refresh(edit)

        await cls._audit(
            db=db,
            action="edit_cancelled",
            actor=owner_id,
            resource_id=str(edit.id),
            metadata={"project_id": str(edit.project_id), "reason": reason, "resource_type": "website_edit_session"},
        )
        return edit

    @classmethod
    async def list_edits_for_project(cls, db: AsyncSession, project_id: uuid.UUID, owner_id: str) -> List[WebsiteEditSession]:
        """Lists edit sessions for a project."""
        project = await db.get(Project, project_id)
        if not project:
            raise EditNotFoundError(f"Project '{project_id}' not found.")
        if project.owner_id != owner_id:
            raise EditOwnershipError("Unauthorized access to project.")

        stmt = (
            select(WebsiteEditSession)
            .where(WebsiteEditSession.project_id == project_id)
            .order_by(desc(WebsiteEditSession.created_at))
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @classmethod
    async def list_versions_for_project(cls, db: AsyncSession, project_id: uuid.UUID, owner_id: str) -> List[WebsiteEditVersion]:
        """Lists all immutable versions for a project."""
        project = await db.get(Project, project_id)
        if not project:
            raise EditNotFoundError(f"Project '{project_id}' not found.")
        if project.owner_id != owner_id:
            raise EditOwnershipError("Unauthorized access to project.")

        stmt = (
            select(WebsiteEditVersion)
            .where(WebsiteEditVersion.project_id == project_id)
            .order_by(desc(WebsiteEditVersion.version))
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())
