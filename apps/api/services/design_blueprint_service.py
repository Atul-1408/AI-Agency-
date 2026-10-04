"""
Phase 6 Stage 6.3 — AI Design System and Site Architecture Blueprint Service.

Responsibilities:
1. Validates source generation readiness (must be COMPLETED).
2. Enforces PRD version and project integrity invariants.
3. Retrieves validated WebsiteSpecification from the source generation artifact.
4. Invokes AIDesignBlueprintProvider with structured prompts and XML boundaries.
5. Deeply validates structured DesignBlueprint output (tokens, components, pages, assets, a11y).
6. Creates and stores DESIGN_BLUEPRINT artifact.
7. Emits structured, immutable audit events via AgentRun.
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    WebsiteGeneration,
    WebsiteGenerationStatus,
)
from schemas.design_blueprint import WebsiteDesignBlueprint
from schemas.website_specification import WebsiteSpecification
from services.design_blueprint_prompt_builder import DesignBlueprintPromptBuilder
from services.design_blueprint_provider import (
    AIDesignBlueprintProvider,
    get_design_blueprint_provider,
)

log = structlog.get_logger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class DesignBlueprintError(Exception):
    """Base exception for design blueprint operations."""
    pass


class DesignBlueprintNotFoundError(DesignBlueprintError):
    """Raised when design blueprint or related record is not found."""
    pass


class DesignBlueprintGenerationNotFoundError(DesignBlueprintNotFoundError):
    """Raised when source generation is not found."""
    pass


class DesignBlueprintOwnershipError(DesignBlueprintError):
    """Raised when owner isolation check fails (IDOR protection)."""
    pass


class DesignBlueprintEligibilityError(DesignBlueprintError):
    """Raised when preconditions for blueprint generation are not met."""
    pass


class DesignBlueprintPRDMismatchError(DesignBlueprintError):
    """Raised when PRD version mismatch is detected."""
    pass


class DesignBlueprintValidationError(DesignBlueprintError):
    """Raised when blueprint validation fails."""
    pass


class DesignBlueprintFailedError(DesignBlueprintError):
    """Raised when blueprint generation execution fails."""
    pass



# ── Service Implementation ───────────────────────────────────────────────────

class DesignBlueprintService:
    """
    Coordinates AI design blueprint generation, output validation, and artifact storage.
    """

    @staticmethod
    async def _audit(
        db: AsyncSession,
        event_name: str,
        status: AgentRunStatus,
        owner_id: str,
        details: Dict[str, Any],
        result: str,
    ) -> None:
        """Record an immutable audit event via AgentRun."""
        payload = {
            "event": event_name,
            "owner": owner_id,
            **details,
        }
        run = AgentRun(
            agent_name=event_name,
            status=status,
            input_data=payload,
            output_data={"result": result},
        )
        db.add(run)
        await db.flush()


    @classmethod
    async def generate_blueprint(
        cls,
        db: AsyncSession,
        generation_id: uuid.UUID,
        owner_id: str,
        provider_override: Optional[AIDesignBlueprintProvider] = None,
    ) -> DesignBlueprint:
        """
        Executes design system and site architecture blueprint generation from a completed generation.
        """
        owner_id_clean = owner_id.lower().strip()

        # Audit initial request
        await cls._audit(
            db=db,
            event_name="design_blueprint_requested",
            status=AgentRunStatus.RUNNING,
            owner_id=owner_id_clean,
            details={"generation_id": str(generation_id)},
            result="processing",
        )

        # 1. Fetch Source Generation & verify ownership
        stmt = (
            select(WebsiteGeneration)
            .options(
                selectinload(WebsiteGeneration.project),
                selectinload(WebsiteGeneration.build_session),
                selectinload(WebsiteGeneration.specification_artifact),
            )
            .where(WebsiteGeneration.id == generation_id)
        )
        res = await db.execute(stmt)
        generation = res.scalar_one_or_none()

        if not generation:
            await cls._audit(
                db=db,
                event_name="design_blueprint_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"generation_id": str(generation_id), "reason": "generation_not_found"},
                result="Generation not found",
            )
            raise DesignBlueprintGenerationNotFoundError(f"Source generation '{generation_id}' not found.")

        if generation.owner_id.lower() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="design_blueprint_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"generation_id": str(generation_id), "reason": "owner_mismatch"},
                result="Access forbidden (IDOR protection)",
            )
            raise DesignBlueprintOwnershipError(
                f"Generation '{generation_id}' does not belong to owner '{owner_id_clean}'."
            )

        # 2. Verify Generation Status == COMPLETED
        if generation.status != WebsiteGenerationStatus.COMPLETED:
            await cls._audit(
                db=db,
                event_name="design_blueprint_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={
                    "generation_id": str(generation_id),
                    "current_status": generation.status.value,
                    "reason": "generation_not_completed",
                },
                result=f"Source generation status '{generation.status.value}' is not COMPLETED",
            )
            raise DesignBlueprintEligibilityError(
                f"Source generation must be in COMPLETED status to generate design blueprint. "
                f"Current status: '{generation.status.value}'."
            )

        session = generation.build_session
        if not session or session.owner_id.lower() != owner_id_clean:
            raise DesignBlueprintOwnershipError("Build session ownership validation failed.")

        if session.status != WebsiteBuildSessionStatus.READY:
            await cls._audit(
                db=db,
                event_name="design_blueprint_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={
                    "generation_id": str(generation_id),
                    "session_id": str(session.id),
                    "session_status": session.status.value,
                    "reason": "session_not_ready",
                },
                result=f"Build session status '{session.status.value}' is not READY",
            )
            raise DesignBlueprintEligibilityError(
                f"Build session status '{session.status.value}' is not eligible for design blueprint. Must be READY."
            )


        project = generation.project
        if not project or project.owner_id.lower() != owner_id_clean:
            raise DesignBlueprintOwnershipError("Project ownership validation failed.")

        if project.project_status not in (ProjectStatus.READY_FOR_BUILD, ProjectStatus.IN_BUILD):
            raise DesignBlueprintEligibilityError(
                f"Project status '{project.project_status.value}' is not eligible for design blueprint."
            )

        # 4. Fetch Approved PRD and verify version match
        stmt_prd = select(ClientPRD).where(ClientPRD.id == generation.source_prd_id)
        prd = (await db.execute(stmt_prd)).scalar_one_or_none()

        if not prd or prd.status != PRDStatus.APPROVED:
            raise DesignBlueprintEligibilityError("Associated PRD is missing or not APPROVED.")

        if project.prd_version != prd.version or generation.source_prd_version != prd.version:
            raise DesignBlueprintPRDMismatchError(
                f"PRD version mismatch: Generation anchors PRD v{generation.source_prd_version}, "
                f"but approved PRD is v{prd.version}."
            )

        # 5. Extract Validated WebsiteSpecification from Artifact
        spec_artifact = generation.specification_artifact
        if not spec_artifact or not spec_artifact.artifact_metadata:
            raise DesignBlueprintEligibilityError("Source generation is missing a validated specification artifact.")

        try:
            spec = WebsiteSpecification.model_validate(spec_artifact.artifact_metadata)
        except Exception as exc:
            raise DesignBlueprintEligibilityError(f"Failed to parse source specification artifact: {exc}") from exc

        # 6. Monotonically increment blueprint_version per source generation
        stmt_max = select(func.max(DesignBlueprint.blueprint_version)).where(
            DesignBlueprint.source_generation_id == generation.id
        )
        max_ver = (await db.execute(stmt_max)).scalar() or 0
        blueprint_version = max_ver + 1

        # 7. Resolve provider
        provider = get_design_blueprint_provider(provider_override)

        # 8. Create DesignBlueprint in PENDING
        blueprint = DesignBlueprint(
            id=uuid.uuid4(),
            build_session_id=session.id,
            project_id=project.id,
            owner_id=owner_id_clean,
            source_generation_id=generation.id,
            source_generation_version=generation.generation_version,
            blueprint_version=blueprint_version,
            status=DesignBlueprintStatus.PENDING,
            blueprint_metadata={},
        )
        db.add(blueprint)
        await db.commit()
        await db.refresh(blueprint)

        # 9. Transition to GENERATING
        blueprint.status = DesignBlueprintStatus.GENERATING
        blueprint.started_at = datetime.now(timezone.utc)
        await db.commit()

        await cls._audit(
            db=db,
            event_name="design_blueprint_started",
            status=AgentRunStatus.RUNNING,
            owner_id=owner_id_clean,
            details={
                "blueprint_id": str(blueprint.id),
                "generation_id": str(generation.id),
                "blueprint_version": blueprint_version,
                "provider": provider.provider_name,
                "model": provider.model_name,
            },
            result="generating",
        )

        try:
            # 10. Prepare Prompt Context
            prd_data = {
                "title": prd.title,
                "version": prd.version,
                "executive_summary": prd.executive_summary,
                "business_overview": prd.business_overview,
                "goals": prd.goals,
                "target_audience": prd.target_audience,
                "sitemap": prd.sitemap,
                "content_requirements": prd.content_requirements,
                "design_requirements": prd.design_requirements,
                "branding_requirements": prd.branding_requirements,
            }

            stmt_reqs = select(ClientRequirement).where(
                ClientRequirement.conversation_id == prd.conversation_id
            )
            reqs = (await db.execute(stmt_reqs)).scalars().all()
            reqs_data = [
                {"category": r.category, "key": r.key, "value": r.value, "status": r.status.value}
                for r in reqs
            ]

            system_prompt, user_prompt = DesignBlueprintPromptBuilder.build_prompts(
                project_name=project.project_name,
                project_slug=project.project_slug,
                source_generation_id=str(generation.id),
                source_generation_version=generation.generation_version,
                prd_data=prd_data,
                specification_data=spec_artifact.artifact_metadata,
                requirements_data=reqs_data,
            )

            provider_context = {
                "specification": spec_artifact.artifact_metadata,
                "blueprint_version": blueprint_version,
                "source_generation_id": str(generation.id),
                "source_generation_version": generation.generation_version,
                "prd_data": prd_data,
            }

            # 11. Execute Provider
            blueprint_spec, provider_meta = await provider.generate_blueprint(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context=provider_context,
            )

            # 12. Transition to VALIDATING
            blueprint.status = DesignBlueprintStatus.VALIDATING
            await db.commit()

            # Ensure blueprint references match source generation
            if blueprint_spec.source_generation_id != str(generation.id):
                raise ValueError("Generated blueprint references invalid source_generation_id.")

            await cls._audit(
                db=db,
                event_name="design_blueprint_validated",
                status=AgentRunStatus.RUNNING,
                owner_id=owner_id_clean,
                details={
                    "blueprint_id": str(blueprint.id),
                    "components_count": len(blueprint_spec.component_taxonomy),
                    "pages_count": len(blueprint_spec.pages),
                },
                result="blueprint_valid",
            )

            # 13. Create DESIGN_BLUEPRINT Artifact
            blueprint_dict = blueprint_spec.model_dump()
            artifact = WebsiteBuildArtifact(
                id=uuid.uuid4(),
                build_session_id=session.id,
                project_id=project.id,
                artifact_type=WebsiteBuildArtifactType.DESIGN_BLUEPRINT,
                artifact_name=f"design_blueprint_v{blueprint_version}.json",
                artifact_version=blueprint_version,
                content_reference=f"generations/{generation.id}/blueprints/{blueprint.id}/design-blueprint",
                artifact_metadata=blueprint_dict,
            )
            db.add(artifact)
            await db.flush()

            # 14. Complete Blueprint
            blueprint.status = DesignBlueprintStatus.COMPLETED
            blueprint.completed_at = datetime.now(timezone.utc)
            blueprint.specification_artifact_id = artifact.id
            blueprint.blueprint_metadata = {
                **provider_meta,
                "components_count": len(blueprint_spec.component_taxonomy),
                "pages_count": len(blueprint_spec.pages),
                "asset_requirements_count": len(blueprint_spec.asset_requirements),
            }
            await db.commit()
            await db.refresh(blueprint)

            await cls._audit(
                db=db,
                event_name="design_blueprint_completed",
                status=AgentRunStatus.COMPLETED,
                owner_id=owner_id_clean,
                details={
                    "blueprint_id": str(blueprint.id),
                    "artifact_id": str(artifact.id),
                    "blueprint_version": blueprint_version,
                },
                result="success",
            )

            return blueprint

        except Exception as exc:
            blueprint.status = DesignBlueprintStatus.FAILED
            blueprint.completed_at = datetime.now(timezone.utc)
            blueprint.error_code = exc.__class__.__name__
            blueprint.error_message = str(exc)
            await db.commit()

            await cls._audit(
                db=db,
                event_name="design_blueprint_failed",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={
                    "blueprint_id": str(blueprint.id),
                    "error_code": blueprint.error_code,
                    "error_message": blueprint.error_message,
                },
                result="failed",
            )

            log.error("design_blueprint_failed", blueprint_id=str(blueprint.id), error=str(exc))
            raise DesignBlueprintFailedError(f"Design blueprint generation failed: {exc}") from exc

    @classmethod
    async def cancel_blueprint(
        cls,
        db: AsyncSession,
        blueprint_id: uuid.UUID,
        owner_id: str,
        reason: Optional[str] = None,
    ) -> DesignBlueprint:
        """Cancels a pending or generating design blueprint."""
        owner_id_clean = owner_id.lower().strip()

        stmt = select(DesignBlueprint).where(DesignBlueprint.id == blueprint_id)
        blueprint = (await db.execute(stmt)).scalar_one_or_none()

        if not blueprint:
            raise DesignBlueprintNotFoundError(f"Design blueprint '{blueprint_id}' not found.")

        if blueprint.owner_id.lower() != owner_id_clean:
            raise DesignBlueprintOwnershipError("Design blueprint does not belong to authenticated owner.")

        if blueprint.status in (
            DesignBlueprintStatus.COMPLETED,
            DesignBlueprintStatus.FAILED,
            DesignBlueprintStatus.CANCELLED,
        ):
            raise DesignBlueprintEligibilityError(
                f"Cannot cancel blueprint in terminal state '{blueprint.status.value}'."
            )

        blueprint.status = DesignBlueprintStatus.CANCELLED
        blueprint.completed_at = datetime.now(timezone.utc)
        blueprint.error_message = reason or "Cancelled by owner"
        await db.commit()
        await db.refresh(blueprint)

        await cls._audit(
            db=db,
            event_name="design_blueprint_cancelled",
            status=AgentRunStatus.CANCELLED,
            owner_id=owner_id_clean,
            details={"blueprint_id": str(blueprint_id), "reason": reason},
            result="cancelled",
        )

        return blueprint

    @classmethod
    async def list_blueprints(
        cls,
        db: AsyncSession,
        generation_id: uuid.UUID,
        owner_id: str,
    ) -> List[DesignBlueprint]:
        """Lists all design blueprints for a generation ordered by version desc."""
        owner_id_clean = owner_id.lower().strip()

        stmt_gen = select(WebsiteGeneration).where(WebsiteGeneration.id == generation_id)
        gen = (await db.execute(stmt_gen)).scalar_one_or_none()
        if not gen:
            raise DesignBlueprintGenerationNotFoundError(f"Generation '{generation_id}' not found.")
        if gen.owner_id.lower() != owner_id_clean:
            raise DesignBlueprintOwnershipError("Generation does not belong to authenticated owner.")

        stmt = (
            select(DesignBlueprint)
            .where(DesignBlueprint.source_generation_id == generation_id)
            .order_by(desc(DesignBlueprint.blueprint_version))
        )
        return list((await db.execute(stmt)).scalars().all())

    @classmethod
    async def get_blueprint(
        cls,
        db: AsyncSession,
        blueprint_id: uuid.UUID,
        owner_id: str,
    ) -> Tuple[DesignBlueprint, Optional[WebsiteDesignBlueprint]]:
        """Retrieves full design blueprint details including validated WebsiteDesignBlueprint."""
        owner_id_clean = owner_id.lower().strip()

        stmt = (
            select(DesignBlueprint)
            .options(
                selectinload(DesignBlueprint.specification_artifact),
                selectinload(DesignBlueprint.project),
            )
            .where(DesignBlueprint.id == blueprint_id)
        )
        blueprint = (await db.execute(stmt)).scalar_one_or_none()

        if not blueprint:
            raise DesignBlueprintNotFoundError(f"Design blueprint '{blueprint_id}' not found.")

        if blueprint.owner_id.lower() != owner_id_clean:
            raise DesignBlueprintOwnershipError("Design blueprint does not belong to authenticated owner.")

        bp_spec: Optional[WebsiteDesignBlueprint] = None
        if blueprint.specification_artifact and blueprint.specification_artifact.artifact_metadata:
            try:
                bp_spec = WebsiteDesignBlueprint.model_validate(
                    blueprint.specification_artifact.artifact_metadata
                )
            except Exception as e:
                log.warning("failed_to_parse_design_blueprint_artifact", error=str(e))

        return blueprint, bp_spec

    cancel_design_blueprint = cancel_blueprint
    create_design_blueprint = generate_blueprint
    get_design_blueprint = get_blueprint
    list_blueprints_for_generation = list_blueprints



