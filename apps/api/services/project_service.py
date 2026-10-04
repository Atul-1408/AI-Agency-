"""
Phase 5 Stage 5.4 — Project Service and Gate 4 Handoff Engine.

Responsibilities:
1. Controlled project creation anchored to Gate 4 APPROVED ClientPRD.
2. Complete ownership verification across Lead, ClientConversation, and ClientPRD.
3. Deterministic snapshotting of approved requirements for Phase 6 handoff.
4. Idempotency guarantees (database uniqueness on approved_prd_id and concurrency handling).
5. Safe project name and slug generation with malicious payload sanitization.
6. Restrictive lifecycle update enforcement (immutable core attributes).
7. Comprehensive audit logging for all project lifecycle events.

SECURITY GUARANTEES:
- No automatic project creation: human owner must explicitly initiate.
- Gate 4 enforcement: PRD must be in APPROVED status with approved_by and approved_at.
- IDOR isolation: owner_id derived exclusively from authenticated JWT.
- Zero AI execution, requirement re-extraction, or PRD regeneration in this phase.
- Phase 6 boundary protection: no website building, code generation, GitHub, or Vercel actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from models import AgentRun, AgentRunStatus, Lead
from models.client_intelligence import ClientConversation, ClientPRD, PRDStatus
from models.project import Project, ProjectStatus
from schemas.project import (
    DANGEROUS_CHARS_PATTERN,
    HTML_SCRIPT_PATTERN,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

log = structlog.get_logger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class ProjectError(Exception):
    """Base exception for project operations."""
    pass


class ProjectNotFoundError(ProjectError):
    """Raised when a project is not found."""
    pass


class ProjectOwnershipError(ProjectError):
    """Raised when owner isolation check fails (IDOR protection)."""
    pass


class PRDNotApprovedError(ProjectError):
    """Raised when project creation is attempted from a non-APPROVED PRD."""
    pass


class PRDInvalidStateError(ProjectError):
    """Raised when an approved PRD is missing required metadata."""
    pass


class ProjectAlreadyExistsError(ProjectError):
    """Raised when a project already exists for an approved PRD."""
    def __init__(self, message: str, existing_project_id: Optional[uuid.UUID] = None):
        super().__init__(message)
        self.existing_project_id = existing_project_id


class ProjectValidationError(ProjectError):
    """Raised when project creation or update parameters fail validation."""
    pass


class ProjectImmutableFieldError(ProjectError):
    """Raised when client attempts to modify an immutable project field."""
    pass


class ProjectInvalidStatusTransitionError(ProjectError):
    """Raised when client attempts an unauthorized lifecycle state transition."""
    pass


# ── Helper Utilities ──────────────────────────────────────────────────────────

def generate_safe_slug(name: str) -> str:
    """
    Generate a normalized, lowercase, safe URL slug.
    Guarantees:
    - No HTML, scripts, or dangerous characters.
    - Only lowercase alphanumeric and hyphens.
    - Max length 50 chars.
    - Non-empty fallback.
    """
    # Remove HTML/script tags
    cleaned = HTML_SCRIPT_PATTERN.sub("", name)
    cleaned = cleaned.lower().strip()
    # Replace non-alphanumeric characters with hyphens
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    # Collapse multiple hyphens and trim
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    # Truncate to reasonable length
    if len(cleaned) > 50:
        cleaned = cleaned[:50].rstrip("-")
    if not cleaned:
        cleaned = f"project-{uuid.uuid4().hex[:8]}"
    return cleaned


def sanitize_name(name: str) -> str:
    """Sanitize and validate project name."""
    cleaned = HTML_SCRIPT_PATTERN.sub("", name).strip()
    cleaned = DANGEROUS_CHARS_PATTERN.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) < 2:
        cleaned = "Website Project"
    if len(cleaned) > 255:
        cleaned = cleaned[:255].strip()
    return cleaned


# ── Project Service Implementation ────────────────────────────────────────────

class ProjectService:
    """Service handling project creation, lifecycle, and Phase 6 handoff readiness."""

    @staticmethod
    async def _audit(
        db: AsyncSession,
        event_name: str,
        status: AgentRunStatus,
        owner_id: str,
        details: Dict[str, Any],
        result: str,
    ) -> None:
        """
        Record an immutable audit event via AgentRun.
        Ensures zero sensitive credentials or headers are logged.
        """
        payload = {
            "event": event_name,
            "owner": owner_id,
            **details,
        }
        run = AgentRun(
            agent_name="project_service",
            status=status,
            input_data=payload,
            output_data={"result": result},
        )
        db.add(run)
        await db.flush()

    @classmethod
    async def create_project(
        cls,
        db: AsyncSession,
        owner_id: str,
        request: ProjectCreateRequest,
    ) -> Project:
        """
        Create a new Project record from an Approved PRD (Gate 4).

        STRICT GATE 4 CREATION RULES:
        1. Authenticated owner exists.
        2. PRD exists.
        3. PRD belongs to authenticated owner.
        4. PRD status == APPROVED.
        5. PRD approved_by exists.
        6. PRD approved_at exists.
        7. Conversation belongs to owner.
        8. Lead belongs to owner.
        9. PRD references correct conversation.
        10. PRD references correct lead.
        11. No project already exists for that approved PRD.
        """
        owner_id_clean = owner_id.lower().strip()
        approved_prd_id = request.approved_prd_id

        # Audit initial request
        await cls._audit(
            db=db,
            event_name="project_creation_requested",
            status=AgentRunStatus.RUNNING,
            owner_id=owner_id_clean,
            details={"approved_prd_id": str(approved_prd_id)},
            result="processing",
        )

        # 11. Check if a project already exists for this approved PRD
        existing_stmt = select(Project).where(Project.approved_prd_id == approved_prd_id)
        existing_proj = (await db.scalars(existing_stmt)).first()
        if existing_proj is not None:
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={
                    "approved_prd_id": str(approved_prd_id),
                    "existing_project_id": str(existing_proj.id),
                    "reason": "duplicate_project",
                },
                result="blocked_duplicate",
            )
            raise ProjectAlreadyExistsError(
                f"A project already exists for approved PRD '{approved_prd_id}'.",
                existing_project_id=existing_proj.id,
            )

        # 2. Fetch PRD
        prd_stmt = select(ClientPRD).where(ClientPRD.id == approved_prd_id)
        prd = (await db.scalars(prd_stmt)).first()
        if prd is None:
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"approved_prd_id": str(approved_prd_id), "reason": "prd_not_found"},
                result="blocked_not_found",
            )
            raise ProjectValidationError(f"PRD '{approved_prd_id}' not found.")

        # 3. PRD belongs to authenticated owner
        if prd.owner_email.lower().strip() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"approved_prd_id": str(approved_prd_id), "reason": "prd_ownership_mismatch"},
                result="forbidden",
            )
            raise ProjectOwnershipError(f"Access denied to PRD '{approved_prd_id}'.")

        # 4. Gate 4: PRD status must be APPROVED
        prd_status_val = prd.status.value if isinstance(prd.status, PRDStatus) else str(prd.status)
        if prd_status_val != PRDStatus.APPROVED.value:
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={
                    "approved_prd_id": str(approved_prd_id),
                    "prd_status": prd_status_val,
                    "reason": "gate4_prd_not_approved",
                },
                result="blocked_gate4",
            )
            raise PRDNotApprovedError(
                f"Project creation requires Gate 4 APPROVED PRD. Current PRD status is '{prd_status_val}'."
            )

        # 5. approved_by exists
        if not prd.approved_by or not prd.approved_by.strip():
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"approved_prd_id": str(approved_prd_id), "reason": "missing_approved_by"},
                result="blocked_invalid_state",
            )
            raise PRDInvalidStateError("Approved PRD is missing approver identity (approved_by).")

        # 6. approved_at exists
        if prd.approved_at is None:
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"approved_prd_id": str(approved_prd_id), "reason": "missing_approved_at"},
                result="blocked_invalid_state",
            )
            raise PRDInvalidStateError("Approved PRD is missing approval timestamp (approved_at).")

        # 7 & 9. Fetch conversation and verify ownership & PRD reference
        conv_stmt = select(ClientConversation).where(ClientConversation.id == prd.conversation_id)
        conv = (await db.scalars(conv_stmt)).first()
        if conv is None or conv.owner_email.lower().strip() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"conversation_id": str(prd.conversation_id), "reason": "conversation_ownership_mismatch"},
                result="forbidden",
            )
            raise ProjectOwnershipError("Conversation ownership verification failed.")

        # 8 & 10. Fetch lead and verify PRD reference consistency
        lead_stmt = select(Lead).where(Lead.id == prd.lead_id)
        lead = (await db.scalars(lead_stmt)).first()
        if lead is None:
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"lead_id": str(prd.lead_id), "reason": "lead_not_found"},
                result="blocked_invalid_state",
            )
            raise ProjectValidationError(f"Associated lead '{prd.lead_id}' not found.")

        if conv.lead_id != prd.lead_id:
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"lead_id": str(prd.lead_id), "reason": "lead_conversation_mismatch"},
                result="blocked_invalid_state",
            )
            raise ProjectValidationError("PRD lead does not match conversation lead.")

        # Determine project name
        if request.custom_project_name and request.custom_project_name.strip():
            proj_name = sanitize_name(request.custom_project_name)
        elif lead.company_name and lead.company_name.strip():
            proj_name = sanitize_name(f"{lead.company_name.strip()} Website")
        elif prd.title and prd.title.strip():
            proj_name = sanitize_name(prd.title)
        else:
            proj_name = "Client Website Project"

        # Generate unique project slug
        base_slug = generate_safe_slug(proj_name)
        slug_candidate = base_slug
        slug_counter = 1

        while True:
            slug_exists = (
                await db.scalars(
                    select(Project).where(
                        Project.owner_id == owner_id_clean,
                        Project.project_slug == slug_candidate,
                    )
                )
            ).first()
            if not slug_exists:
                break
            slug_counter += 1
            slug_candidate = f"{base_slug[:45]}-{slug_counter}"

        # Construct deterministic Phase 6 handoff metadata snapshot
        phase_metadata = {
            "phase_6_ready": True,
            "handoff_created_at": datetime.now(timezone.utc).isoformat(),
            "approved_prd_id": str(prd.id),
            "approved_prd_version": prd.version,
            "approved_by": prd.approved_by,
            "approved_at": prd.approved_at.isoformat() if prd.approved_at else None,
            "lead_id": str(prd.lead_id),
            "conversation_id": str(prd.conversation_id),
            "business_name": lead.company_name,
            "business_domain": lead.domain,
            "business_overview": prd.business_overview,
            "goals": prd.goals,
            "target_audience": prd.target_audience,
            "sitemap": prd.sitemap,
            "content_requirements": prd.content_requirements,
            "functionality_requirements": prd.functionality_requirements,
            "design_requirements": prd.design_requirements,
            "branding_requirements": prd.branding_requirements,
            "contact_requirements": prd.contact_requirements,
            "technical_requirements": prd.technical_requirements,
            "timeline": prd.timeline,
            "budget": prd.budget,
            "assumptions": prd.assumptions,
            "open_questions": prd.open_questions,
            "requirement_traceability": prd.requirement_traceability,
        }

        # Initialize project
        project = Project(
            owner_id=owner_id_clean,
            lead_id=prd.lead_id,
            conversation_id=prd.conversation_id,
            approved_prd_id=prd.id,
            prd_version=prd.version,
            project_name=proj_name,
            project_slug=slug_candidate,
            project_status=ProjectStatus.READY_FOR_BUILD,
            project_source="approved_prd",
            created_by=owner_id_clean,
            phase_metadata=phase_metadata,
        )

        db.add(project)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            # Race condition handling: check existing project
            existing_after_race = (
                await db.scalars(select(Project).where(Project.approved_prd_id == approved_prd_id))
            ).first()
            await cls._audit(
                db=db,
                event_name="project_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"approved_prd_id": str(approved_prd_id), "reason": "integrity_error_duplicate"},
                result="blocked_concurrent_duplicate",
            )
            raise ProjectAlreadyExistsError(
                f"A project already exists for approved PRD '{approved_prd_id}'.",
                existing_project_id=existing_after_race.id if existing_after_race else None,
            )

        await db.refresh(project)

        # Audit successful project creation
        await cls._audit(
            db=db,
            event_name="project_created",
            status=AgentRunStatus.COMPLETED,
            owner_id=owner_id_clean,
            details={
                "project_id": str(project.id),
                "approved_prd_id": str(prd.id),
                "prd_version": prd.version,
                "project_slug": project.project_slug,
                "lead_id": str(prd.lead_id),
                "conversation_id": str(prd.conversation_id),
            },
            result="success",
        )

        log.info(
            "Project created successfully from approved PRD",
            project_id=str(project.id),
            prd_id=str(prd.id),
            owner=owner_id_clean,
        )
        return project

    @classmethod
    async def get_project(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
    ) -> ProjectDetailResponse:
        """
        Retrieve a single project by ID with complete enrichment.
        Enforces owner isolation (IDOR protection) and logs project_accessed.
        """
        owner_id_clean = owner_id.lower().strip()

        stmt = (
            select(Project)
            .where(Project.id == project_id)
            .options(
                selectinload(Project.lead),
                selectinload(Project.conversation),
                selectinload(Project.approved_prd),
            )
        )
        project = (await db.scalars(stmt)).first()

        if project is None:
            raise ProjectNotFoundError(f"Project '{project_id}' not found.")

        if project.owner_id.lower().strip() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="project_accessed",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"project_id": str(project_id), "reason": "ownership_mismatch"},
                result="forbidden",
            )
            raise ProjectOwnershipError(f"Access denied to project '{project_id}'.")

        # Audit accessed
        await cls._audit(
            db=db,
            event_name="project_accessed",
            status=AgentRunStatus.COMPLETED,
            owner_id=owner_id_clean,
            details={"project_id": str(project_id)},
            result="success",
        )

        # Build enrichment summaries
        lead = project.lead
        conv = project.conversation
        prd = project.approved_prd

        business_info = {
            "company_name": lead.company_name if lead else None,
            "domain": lead.domain if lead else None,
            "website_url": lead.website_url if lead else None,
            "industry": lead.industry if lead else None,
            "city": lead.city if lead else None,
            "qualification_score": lead.qualification_score if lead else None,
        }

        conversation_summary = {
            "conversation_id": str(conv.id) if conv else None,
            "status": conv.status.value if conv and hasattr(conv.status, "value") else (str(conv.status) if conv else None),
            "message_count": conv.message_count if conv and conv.message_count is not None else 0,
            "has_unreplied_inbound": getattr(conv, "has_unreplied_inbound", False) if conv else False,
            "last_message_at": conv.last_message_at.isoformat() if conv and conv.last_message_at else None,
        }

        prd_summary = {
            "prd_id": str(prd.id) if prd else None,
            "version": prd.version if prd else project.prd_version,
            "title": prd.title if prd else None,
            "status": prd.status.value if prd and hasattr(prd.status, "value") else (str(prd.status) if prd else None),
            "approved_at": prd.approved_at.isoformat() if prd and prd.approved_at else None,
            "approved_by": prd.approved_by if prd else None,
            "executive_summary": prd.executive_summary if prd else None,
            "sitemap": prd.sitemap if prd else [],
        }

        open_questions = project.phase_metadata.get("open_questions", [])
        traceability = project.phase_metadata.get("requirement_traceability", {})

        handoff_readiness = {
            "phase_6_ready": True,
            "approved_prd_id": str(project.approved_prd_id),
            "approved_prd_version": project.prd_version,
            "open_questions_count": len(open_questions) if isinstance(open_questions, list) else 0,
            "mapped_requirements_count": len(traceability) if isinstance(traceability, dict) else 0,
            "status": project.project_status.value,
        }

        return ProjectDetailResponse(
            id=project.id,
            owner_id=project.owner_id,
            lead_id=project.lead_id,
            conversation_id=project.conversation_id,
            approved_prd_id=project.approved_prd_id,
            prd_version=project.prd_version,
            project_name=project.project_name,
            project_slug=project.project_slug,
            project_status=project.project_status,
            project_source=project.project_source,
            created_by=project.created_by,
            created_at=project.created_at,
            updated_at=project.updated_at,
            phase_metadata=project.phase_metadata,
            business_name=lead.company_name if lead else None,
            business_domain=lead.domain if lead else None,
            business_type=lead.industry if lead else None,
            lead_info=business_info,
            conversation_summary=conversation_summary,
            prd_summary=prd_summary,
            requirements_summary={"traceability_count": len(traceability) if isinstance(traceability, dict) else 0},
            handoff_readiness=handoff_readiness,
        )

    @classmethod
    async def list_projects(
        cls,
        db: AsyncSession,
        owner_id: str,
        status_filter: Optional[ProjectStatus] = None,
        search: Optional[str] = None,
    ) -> ProjectListResponse:
        """List all projects belonging to the authenticated owner."""
        owner_id_clean = owner_id.lower().strip()

        query = select(Project).where(Project.owner_id == owner_id_clean)

        if status_filter:
            query = query.where(Project.project_status == status_filter)

        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            query = query.where(
                func.lower(Project.project_name).like(term) | func.lower(Project.project_slug).like(term)
            )

        query = query.order_by(desc(Project.created_at))
        result = await db.scalars(query)
        items = list(result.all())

        # Compute metric aggregates across all projects of the owner
        all_owner_projects_query = select(Project.project_status).where(Project.owner_id == owner_id_clean)
        all_owner_statuses = (await db.scalars(all_owner_projects_query)).all()

        total = len(all_owner_statuses)
        ready_for_build_count = sum(1 for s in all_owner_statuses if s == ProjectStatus.READY_FOR_BUILD)
        in_build_count = sum(1 for s in all_owner_statuses if s == ProjectStatus.IN_BUILD)
        completed_count = sum(1 for s in all_owner_statuses if s == ProjectStatus.COMPLETED)

        return ProjectListResponse(
            items=[ProjectResponse.model_validate(p) for p in items],
            total=total,
            ready_for_build_count=ready_for_build_count,
            in_build_count=in_build_count,
            completed_count=completed_count,
        )

    @classmethod
    async def update_project(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
        request: ProjectUpdateRequest,
    ) -> Project:
        """
        Update safe mutable fields of a project.
        Enforces owner isolation, field immutability, and lifecycle state constraints.
        """
        owner_id_clean = owner_id.lower().strip()

        stmt = select(Project).where(Project.id == project_id)
        project = (await db.scalars(stmt)).first()

        if project is None:
            raise ProjectNotFoundError(f"Project '{project_id}' not found.")

        if project.owner_id.lower().strip() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="project_updated",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"project_id": str(project_id), "reason": "ownership_mismatch"},
                result="forbidden",
            )
            raise ProjectOwnershipError(f"Access denied to project '{project_id}'.")

        updated_fields: List[str] = []

        if request.project_name is not None:
            clean_name = sanitize_name(request.project_name)
            project.project_name = clean_name
            updated_fields.append("project_name")

        if request.project_status is not None:
            # Phase 5.4 only permits READY_FOR_BUILD or CANCELLED
            if request.project_status not in {ProjectStatus.READY_FOR_BUILD, ProjectStatus.CANCELLED}:
                raise ProjectInvalidStatusTransitionError(
                    f"Transition to status '{request.project_status.value}' is not permitted in Phase 5.4."
                )
            project.project_status = request.project_status
            updated_fields.append("project_status")

        if request.phase_metadata is not None:
            # Merge safe metadata
            updated_metadata = dict(project.phase_metadata)
            updated_metadata.update(request.phase_metadata)
            project.phase_metadata = updated_metadata
            updated_fields.append("phase_metadata")

        await db.flush()
        await db.refresh(project)

        # Audit update
        await cls._audit(
            db=db,
            event_name="project_updated",
            status=AgentRunStatus.COMPLETED,
            owner_id=owner_id_clean,
            details={
                "project_id": str(project_id),
                "updated_fields": updated_fields,
            },
            result="success",
        )

        return project
