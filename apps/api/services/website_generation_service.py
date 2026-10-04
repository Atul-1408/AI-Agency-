"""
Phase 6 Stage 6.2 — AI Website Generation Service.

Responsibilities:
1. Validates build session readiness and Gate 4 PRD preconditions.
2. Enforces PRD version immutability (version snapshot must match approved PRD).
3. Gathers authoritative requirements and constructs prompt with XML boundaries.
4. Invokes the AI generation provider with error handling and fallback stability.
5. Deeply validates structured output against WebsiteSpecification schema.
6. Stores validated specification as a WEBSITE_SPECIFICATION artifact.
7. Tracks generation lifecycle (PENDING -> GENERATING -> VALIDATING -> COMPLETED / FAILED / CANCELLED).
8. Logs granular audit records (requested, started, validated, completed, failed, cancelled, blocked).

STRICT ARCHITECTURAL BOUNDARIES:
- ZERO executable code generation (no React, Next.js, HTML, CSS, JSX, TSX).
- ZERO GitHub repository creation or pushes.
- ZERO Vercel or cloud deployments.
- Output is strictly planning data (WebsiteSpecification).
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
from models.client_intelligence import (
    ClientConversation,
    ClientPRD,
    ClientRequirement,
    ClientRequirementEvidence,
    PRDStatus,
)
from models.project import Project, ProjectStatus
from models.website_builder import (
    WebsiteBuildArtifact,
    WebsiteBuildArtifactType,
    WebsiteBuildSession,
    WebsiteBuildSessionStatus,
    WebsiteGeneration,
    WebsiteGenerationStatus,
)
from schemas.website_specification import WebsiteSpecification
from services.website_generation_prompt_builder import WebsiteGenerationPromptBuilder
from services.website_generator_provider import (
    AIProviderError,
    AIWebsiteGenerationProvider,
    get_website_generation_provider,
)

log = structlog.get_logger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class WebsiteGenerationError(Exception):
    """Base exception for WebsiteGenerationService errors."""
    pass


class WebsiteGenerationSessionNotFoundError(WebsiteGenerationError):
    """Raised when build session is not found."""
    pass


class WebsiteGenerationOwnershipError(WebsiteGenerationError):
    """Raised when owner isolation check fails (IDOR protection)."""
    pass


class WebsiteGenerationEligibilityError(WebsiteGenerationError):
    """Raised when preconditions for generation are not met (e.g. session not READY)."""
    pass


class WebsiteGenerationPRDMismatchError(WebsiteGenerationError):
    """Raised when PRD version does not match build session anchor."""
    pass


class WebsiteGenerationFailedError(WebsiteGenerationError):
    """Raised when generation execution fails."""
    pass


class WebsiteGenerationNotFoundError(WebsiteGenerationError):
    """Raised when generation record is not found."""
    pass


# ── Generation Service ────────────────────────────────────────────────────────

class WebsiteGenerationService:
    """
    Coordinates AI website specification generation, output validation, and artifact storage.
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
            agent_name="website_generation_service",
            status=status,
            input_data=payload,
            output_data={"result": result},
        )
        db.add(run)
        await db.flush()

    @classmethod
    async def generate_specification(
        cls,
        db: AsyncSession,
        session_id: uuid.UUID,
        owner_id: str,
        provider_override: Optional[AIWebsiteGenerationProvider] = None,
    ) -> WebsiteGeneration:
        """
        Executes AI website specification generation for a READY build session.
        """
        owner_id_clean = owner_id.lower().strip()

        # Audit initial request
        await cls._audit(
            db=db,
            event_name="website_generation_requested",
            status=AgentRunStatus.RUNNING,
            owner_id=owner_id_clean,
            details={"session_id": str(session_id)},
            result="processing",
        )

        # 1. Fetch Build Session & verify ownership
        stmt = (
            select(WebsiteBuildSession)
            .options(selectinload(WebsiteBuildSession.project))
            .where(WebsiteBuildSession.id == session_id)
        )
        res = await db.execute(stmt)
        session = res.scalar_one_or_none()

        if not session:
            await cls._audit(
                db=db,
                event_name="website_generation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"session_id": str(session_id), "reason": "session_not_found"},
                result="Session not found",
            )
            raise WebsiteGenerationSessionNotFoundError(f"Build session '{session_id}' not found.")

        if session.owner_id.lower() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="website_generation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"session_id": str(session_id), "reason": "owner_mismatch"},
                result="Access forbidden (IDOR protection)",
            )
            raise WebsiteGenerationOwnershipError(
                f"Build session '{session_id}' does not belong to owner '{owner_id_clean}'."
            )

        # 2. Verify Session Status == READY
        if session.status != WebsiteBuildSessionStatus.READY:
            await cls._audit(
                db=db,
                event_name="website_generation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={
                    "session_id": str(session_id),
                    "current_status": session.status.value,
                    "reason": "session_not_ready",
                },
                result=f"Session status '{session.status.value}' is not READY",
            )
            raise WebsiteGenerationEligibilityError(
                f"Build session must be in READY status to trigger website specification generation. "
                f"Current status: '{session.status.value}'."
            )

        # 3. Fetch Project & verify ownership and status
        project = session.project
        if not project:
            stmt_proj = select(Project).where(Project.id == session.project_id)
            res_proj = await db.execute(stmt_proj)
            project = res_proj.scalar_one_or_none()

        if not project or project.owner_id.lower() != owner_id_clean:
            raise WebsiteGenerationOwnershipError("Project ownership validation failed.")

        if project.project_status not in (ProjectStatus.READY_FOR_BUILD, ProjectStatus.IN_BUILD):
            raise WebsiteGenerationEligibilityError(
                f"Project status '{project.project_status.value}' is not eligible for website generation."
            )

        if not project.approved_prd_id:
            raise WebsiteGenerationEligibilityError("Project does not have an approved PRD reference.")

        # 4. Fetch Approved PRD & verify Gate 4 approval metadata
        stmt_prd = select(ClientPRD).where(ClientPRD.id == project.approved_prd_id)
        res_prd = await db.execute(stmt_prd)
        prd = res_prd.scalar_one_or_none()

        if not prd:
            raise WebsiteGenerationEligibilityError(f"Approved PRD '{project.approved_prd_id}' not found.")

        if prd.status != PRDStatus.APPROVED:
            raise WebsiteGenerationEligibilityError(
                f"Associated PRD status is '{prd.status.value}', expected APPROVED."
            )

        if not prd.approved_at or not prd.approved_by:
            raise WebsiteGenerationEligibilityError("Associated PRD is missing Gate 4 approval metadata.")

        # 5. Version Invariant Check: Build session anchor must match approved PRD version
        if project.prd_version != prd.version:
            raise WebsiteGenerationPRDMismatchError(
                f"PRD version mismatch: Project anchors PRD v{project.prd_version}, "
                f"but approved PRD is v{prd.version}."
            )

        # 6. Determine Generation Version (sequential monotonic increment per build session)
        stmt_max = select(func.max(WebsiteGeneration.generation_version)).where(
            WebsiteGeneration.build_session_id == session.id
        )
        max_ver = (await db.execute(stmt_max)).scalar() or 0
        generation_version = max_ver + 1

        # 7. Resolve provider
        provider = get_website_generation_provider(provider_override)

        # 8. Create Generation record in PENDING
        generation = WebsiteGeneration(
            id=uuid.uuid4(),
            build_session_id=session.id,
            project_id=project.id,
            owner_id=owner_id_clean,
            source_prd_id=prd.id,
            source_prd_version=prd.version,
            generation_version=generation_version,
            status=WebsiteGenerationStatus.PENDING,
            provider=provider.provider_name,
            model=provider.model_name,
            generation_metadata={},
        )
        db.add(generation)
        await db.commit()
        await db.refresh(generation)

        # 9. Transition to GENERATING
        generation.status = WebsiteGenerationStatus.GENERATING
        generation.started_at = datetime.now(timezone.utc)
        await db.commit()

        await cls._audit(
            db=db,
            event_name="website_generation_started",
            status=AgentRunStatus.RUNNING,
            owner_id=owner_id_clean,
            details={
                "session_id": str(session.id),
                "generation_id": str(generation.id),
                "generation_version": generation_version,
                "provider": provider.provider_name,
                "model": provider.model_name,
            },
            result="generating",
        )

        try:
            # 10. Gather PRD & Requirements Context
            prd_data = {
                "title": prd.title,
                "version": prd.version,
                "executive_summary": prd.executive_summary,
                "business_overview": prd.business_overview,
                "goals": prd.goals,
                "target_audience": prd.target_audience,
                "sitemap": prd.sitemap,
                "content_requirements": prd.content_requirements,
                "functionality_requirements": prd.functionality_requirements,
                "design_requirements": prd.design_requirements,
                "branding_requirements": prd.branding_requirements,
                "technical_requirements": prd.technical_requirements,
                "assumptions": prd.assumptions,
                "open_questions": prd.open_questions,
            }

            # Fetch confirmed requirements
            stmt_reqs = select(ClientRequirement).where(
                ClientRequirement.conversation_id == prd.conversation_id
            )
            reqs = (await db.execute(stmt_reqs)).scalars().all()
            reqs_data = [
                {
                    "id": str(r.id),
                    "category": r.category,
                    "key": r.key,
                    "value": r.value,
                    "status": r.status.value,
                }
                for r in reqs
            ]

            # Construct Prompts
            system_prompt, user_prompt = WebsiteGenerationPromptBuilder.build_prompts(
                project_name=project.project_name,
                project_slug=project.project_slug,
                source_prd_id=str(prd.id),
                source_prd_version=prd.version,
                prd_data=prd_data,
                requirements_data=reqs_data,
            )

            # Context for provider
            provider_context = {
                "project_name": project.project_name,
                "project_slug": project.project_slug,
                "source_prd_id": str(prd.id),
                "source_prd_version": prd.version,
                "generation_version": generation_version,
                "prd_data": prd_data,
                "requirements": reqs_data,
            }

            # 11. Execute AI Provider
            spec, provider_meta = await provider.generate_specification(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context=provider_context,
            )

            # 12. Transition to VALIDATING
            generation.status = WebsiteGenerationStatus.VALIDATING
            await db.commit()

            # Ensure spec source PRD and version matches authoritative record
            if str(spec.source_prd_id) != str(prd.id) or spec.source_prd_version != prd.version:
                raise ValueError("Specification output contains mismatched PRD reference.")

            await cls._audit(
                db=db,
                event_name="website_generation_validated",
                status=AgentRunStatus.RUNNING,
                owner_id=owner_id_clean,
                details={
                    "generation_id": str(generation.id),
                    "pages_count": len(spec.pages),
                    "navigation_count": len(spec.navigation),
                },
                result="specification_valid",
            )

            # 13. Create WEBSITE_SPECIFICATION Artifact
            spec_dict = spec.model_dump()
            artifact = WebsiteBuildArtifact(
                id=uuid.uuid4(),
                build_session_id=session.id,
                project_id=project.id,
                artifact_type=WebsiteBuildArtifactType.WEBSITE_SPECIFICATION,
                artifact_name=f"website_specification_v{generation_version}.json",
                artifact_version=generation_version,
                content_reference=f"build-sessions/{session.id}/generations/{generation.id}/specification",
                artifact_metadata=spec_dict,
            )
            db.add(artifact)
            await db.flush()

            # 14. Complete Generation
            generation.status = WebsiteGenerationStatus.COMPLETED
            generation.completed_at = datetime.now(timezone.utc)
            generation.specification_artifact_id = artifact.id
            generation.generation_metadata = {
                **provider_meta,
                "pages_count": len(spec.pages),
                "sections_count": sum(len(p.sections) for p in spec.pages),
            }
            await db.commit()
            await db.refresh(generation)

            await cls._audit(
                db=db,
                event_name="website_generation_completed",
                status=AgentRunStatus.COMPLETED,
                owner_id=owner_id_clean,
                details={
                    "generation_id": str(generation.id),
                    "artifact_id": str(artifact.id),
                    "generation_version": generation_version,
                    "pages_count": len(spec.pages),
                },
                result="success",
            )

            return generation

        except Exception as exc:
            # Mark generation as FAILED
            generation.status = WebsiteGenerationStatus.FAILED
            generation.completed_at = datetime.now(timezone.utc)
            generation.error_code = exc.__class__.__name__
            generation.error_message = str(exc)
            await db.commit()

            await cls._audit(
                db=db,
                event_name="website_generation_failed",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={
                    "generation_id": str(generation.id),
                    "error_code": generation.error_code,
                    "error_message": generation.error_message,
                },
                result="failed",
            )

            log.error("website_generation_failed", generation_id=str(generation.id), error=str(exc))
            raise WebsiteGenerationFailedError(f"Website generation failed: {exc}") from exc

    @classmethod
    async def cancel_generation(
        cls,
        db: AsyncSession,
        generation_id: uuid.UUID,
        owner_id: str,
        reason: Optional[str] = None,
    ) -> WebsiteGeneration:
        """
        Cancels an in-flight or pending generation attempt.
        """
        owner_id_clean = owner_id.lower().strip()

        stmt = select(WebsiteGeneration).where(WebsiteGeneration.id == generation_id)
        res = await db.execute(stmt)
        generation = res.scalar_one_or_none()

        if not generation:
            raise WebsiteGenerationNotFoundError(f"Generation '{generation_id}' not found.")

        if generation.owner_id.lower() != owner_id_clean:
            raise WebsiteGenerationOwnershipError("Generation does not belong to authenticated owner.")

        if generation.status in (
            WebsiteGenerationStatus.COMPLETED,
            WebsiteGenerationStatus.FAILED,
            WebsiteGenerationStatus.CANCELLED,
        ):
            raise WebsiteGenerationEligibilityError(
                f"Cannot cancel generation in terminal state '{generation.status.value}'."
            )

        generation.status = WebsiteGenerationStatus.CANCELLED
        generation.completed_at = datetime.now(timezone.utc)
        generation.error_message = reason or "Cancelled by owner"
        await db.commit()
        await db.refresh(generation)

        await cls._audit(
            db=db,
            event_name="website_generation_cancelled",
            status=AgentRunStatus.CANCELLED,
            owner_id=owner_id_clean,
            details={"generation_id": str(generation_id), "reason": reason},
            result="cancelled",
        )

        return generation

    @classmethod
    async def list_generations(
        cls,
        db: AsyncSession,
        session_id: uuid.UUID,
        owner_id: str,
    ) -> List[WebsiteGeneration]:
        """
        Lists all generations for a build session ordered by version desc.
        """
        owner_id_clean = owner_id.lower().strip()

        # Verify session exists and belongs to owner
        stmt_sess = select(WebsiteBuildSession).where(WebsiteBuildSession.id == session_id)
        session = (await db.execute(stmt_sess)).scalar_one_or_none()
        if not session:
            raise WebsiteGenerationSessionNotFoundError(f"Build session '{session_id}' not found.")
        if session.owner_id.lower() != owner_id_clean:
            raise WebsiteGenerationOwnershipError("Build session does not belong to authenticated owner.")

        stmt = (
            select(WebsiteGeneration)
            .where(WebsiteGeneration.build_session_id == session_id)
            .order_by(desc(WebsiteGeneration.generation_version))
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @classmethod
    async def get_generation(
        cls,
        db: AsyncSession,
        generation_id: uuid.UUID,
        owner_id: str,
    ) -> Tuple[WebsiteGeneration, Optional[WebsiteSpecification]]:
        """
        Retrieves a generation and its associated WebsiteSpecification if completed.
        """
        owner_id_clean = owner_id.lower().strip()

        stmt = (
            select(WebsiteGeneration)
            .options(
                selectinload(WebsiteGeneration.specification_artifact),
                selectinload(WebsiteGeneration.project),
            )
            .where(WebsiteGeneration.id == generation_id)
        )
        res = await db.execute(stmt)
        generation = res.scalar_one_or_none()

        if not generation:
            raise WebsiteGenerationNotFoundError(f"Generation '{generation_id}' not found.")

        if generation.owner_id.lower() != owner_id_clean:
            raise WebsiteGenerationOwnershipError("Generation does not belong to authenticated owner.")

        spec: Optional[WebsiteSpecification] = None
        if generation.specification_artifact and generation.specification_artifact.artifact_metadata:
            try:
                spec = WebsiteSpecification.model_validate(
                    generation.specification_artifact.artifact_metadata
                )
            except Exception as e:
                log.warning("failed_to_parse_specification_artifact", error=str(e))

        return generation, spec
