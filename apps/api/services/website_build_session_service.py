"""
Phase 6 Stage 6.1 — AI Website Build Session Service.

Responsibilities:
1. Validate project eligibility and Gate 4 approved PRD invariants.
2. Controlled build session creation with exact PRD version snapshot.
3. Strict owner isolation (IDOR protection).
4. Active session idempotency (at most one active build session per project).
5. Explicit, validated state machine transitions.
6. Build artifact storage and PRD snapshot preservation.
7. Comprehensive audit logging for all lifecycle events.

STRICT PHASE BOUNDARY:
- NO AI website generation, NO code generation, NO HTML/CSS generation.
- NO GitHub, Vercel, or deployment execution.
- Build sessions establish the controlled workspace boundary for future phases.
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
from models.client_intelligence import ClientPRD, PRDStatus
from models.project import Project, ProjectStatus
from models.website_builder import (
    ACTIVE_BUILD_STATUSES,
    TERMINAL_BUILD_STATUSES,
    WebsiteBuildArtifact,
    WebsiteBuildArtifactType,
    WebsiteBuildSession,
    WebsiteBuildSessionStatus,
)
from schemas.website_builder import (
    WebsiteBuildArtifactResponse,
    WebsiteBuildSessionDetailResponse,
    WebsiteBuildSessionListResponse,
    WebsiteBuildSessionResponse,
)

log = structlog.get_logger(__name__)


# ── Domain Exceptions ─────────────────────────────────────────────────────────

class BuildSessionError(Exception):
    """Base exception for build session operations."""
    pass


class BuildSessionNotFoundError(BuildSessionError):
    """Raised when a build session is not found."""
    pass


class BuildSessionOwnershipError(BuildSessionError):
    """Raised when owner isolation check fails (IDOR protection)."""
    pass


class BuildSessionProjectIneligibleError(BuildSessionError):
    """Raised when project is not in a valid state (e.g. not READY_FOR_BUILD)."""
    pass


class BuildSessionPRDIneligibleError(BuildSessionError):
    """Raised when associated PRD is missing, not approved, or corrupt."""
    pass


class BuildSessionInvalidStateTransitionError(BuildSessionError):
    """Raised when an invalid status transition is requested."""
    pass


class BuildSessionTerminalStateError(BuildSessionError):
    """Raised when attempting to modify a terminal build session."""
    pass


# ── State Machine Transition Graph ────────────────────────────────────────────

VALID_STATE_TRANSITIONS: Dict[WebsiteBuildSessionStatus, set[WebsiteBuildSessionStatus]] = {
    WebsiteBuildSessionStatus.CREATED: {
        WebsiteBuildSessionStatus.PLANNED,
        WebsiteBuildSessionStatus.CANCELLED,
    },
    WebsiteBuildSessionStatus.PLANNED: {
        WebsiteBuildSessionStatus.READY,
        WebsiteBuildSessionStatus.CANCELLED,
    },
    WebsiteBuildSessionStatus.READY: {
        WebsiteBuildSessionStatus.IN_PROGRESS,
        WebsiteBuildSessionStatus.CANCELLED,
    },
    WebsiteBuildSessionStatus.IN_PROGRESS: {
        WebsiteBuildSessionStatus.PAUSED,
        WebsiteBuildSessionStatus.COMPLETED,
        WebsiteBuildSessionStatus.FAILED,
    },
    WebsiteBuildSessionStatus.PAUSED: {
        WebsiteBuildSessionStatus.IN_PROGRESS,
        WebsiteBuildSessionStatus.CANCELLED,
    },
    WebsiteBuildSessionStatus.FAILED: set(),       # Terminal
    WebsiteBuildSessionStatus.COMPLETED: set(),    # Terminal
    WebsiteBuildSessionStatus.CANCELLED: set(),    # Terminal
}


# ── Service Implementation ────────────────────────────────────────────────────

class WebsiteBuildSessionService:
    """Service governing build session creation, lifecycle transitions, and artifact references."""

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
            agent_name="website_build_session_service",
            status=status,
            input_data=payload,
            output_data={"result": result},
        )
        db.add(run)
        await db.flush()

    @classmethod
    async def get_or_create_build_session(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
    ) -> Tuple[WebsiteBuildSession, bool]:
        """
        Create a new build session for a project or return an existing active one.

        Returns (session, created: bool).
        """
        owner_id_clean = owner_id.lower().strip()

        # Audit requested event
        await cls._audit(
            db=db,
            event_name="build_session_creation_requested",
            status=AgentRunStatus.RUNNING,
            owner_id=owner_id_clean,
            details={"project_id": str(project_id)},
            result="processing",
        )

        # 1. Fetch project & verify ownership
        proj_stmt = select(Project).where(Project.id == project_id)
        project = (await db.scalars(proj_stmt)).first()

        if project is None:
            await cls._audit(
                db=db,
                event_name="build_session_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"project_id": str(project_id), "reason": "project_not_found"},
                result="blocked_not_found",
            )
            raise BuildSessionProjectIneligibleError(f"Project '{project_id}' not found.")

        if project.owner_id.lower().strip() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="build_session_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"project_id": str(project_id), "reason": "project_ownership_mismatch"},
                result="forbidden",
            )
            raise BuildSessionOwnershipError(f"Access denied to project '{project_id}'.")

        # 2. Check project status eligibility
        if project.project_status != ProjectStatus.READY_FOR_BUILD:
            await cls._audit(
                db=db,
                event_name="build_session_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={
                    "project_id": str(project_id),
                    "project_status": project.project_status.value,
                    "reason": "project_status_not_ready_for_build",
                },
                result="blocked_ineligible",
            )
            raise BuildSessionProjectIneligibleError(
                f"Project status is '{project.project_status.value}'. "
                f"Build sessions can only be created when project status is 'ready_for_build'."
            )

        # 3. Check approved PRD
        if not project.approved_prd_id:
            await cls._audit(
                db=db,
                event_name="build_session_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"project_id": str(project_id), "reason": "missing_approved_prd_reference"},
                result="blocked_ineligible",
            )
            raise BuildSessionPRDIneligibleError("Project has no approved PRD referenced.")

        prd_stmt = select(ClientPRD).where(ClientPRD.id == project.approved_prd_id)
        prd = (await db.scalars(prd_stmt)).first()

        if prd is None:
            await cls._audit(
                db=db,
                event_name="build_session_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"project_id": str(project_id), "reason": "approved_prd_not_found"},
                result="blocked_ineligible",
            )
            raise BuildSessionPRDIneligibleError("Approved PRD record could not be found.")

        if prd.owner_email.lower().strip() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="build_session_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"project_id": str(project_id), "reason": "prd_ownership_mismatch"},
                result="forbidden",
            )
            raise BuildSessionOwnershipError("Approved PRD does not belong to authenticated owner.")

        prd_status_val = prd.status.value if isinstance(prd.status, PRDStatus) else str(prd.status)
        if prd_status_val != PRDStatus.APPROVED.value:
            await cls._audit(
                db=db,
                event_name="build_session_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"project_id": str(project_id), "prd_status": prd_status_val, "reason": "prd_not_approved"},
                result="blocked_ineligible",
            )
            raise BuildSessionPRDIneligibleError(f"PRD is in '{prd_status_val}' status; must be APPROVED.")

        if not prd.approved_by or prd.approved_at is None:
            await cls._audit(
                db=db,
                event_name="build_session_creation_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"project_id": str(project_id), "reason": "prd_missing_approval_metadata"},
                result="blocked_ineligible",
            )
            raise BuildSessionPRDIneligibleError("Approved PRD is missing approval metadata (approved_by or approved_at).")

        # 4. Idempotency: check if an active build session already exists
        active_stmt = (
            select(WebsiteBuildSession)
            .where(
                WebsiteBuildSession.project_id == project_id,
                WebsiteBuildSession.owner_id == owner_id_clean,
                WebsiteBuildSession.status.in_(ACTIVE_BUILD_STATUSES),
            )
            .order_by(desc(WebsiteBuildSession.build_version))
        )
        existing_active = (await db.scalars(active_stmt)).first()

        if existing_active is not None:
            log.info(
                "Returning existing active build session for project",
                project_id=str(project_id),
                session_id=str(existing_active.id),
                status=existing_active.status.value,
            )
            return existing_active, False

        # 5. Compute next build version
        all_sessions_stmt = select(WebsiteBuildSession.build_version).where(
            WebsiteBuildSession.project_id == project_id
        )
        existing_versions = (await db.scalars(all_sessions_stmt)).all()
        next_version = (max(existing_versions) + 1) if existing_versions else 1

        # 6. Initialize snapshot metadata
        snapshot_metadata = {
            "approved_prd_id": str(prd.id),
            "approved_prd_version": prd.version,
            "approved_by": prd.approved_by,
            "approved_at": prd.approved_at.isoformat() if prd.approved_at else None,
            "project_name": project.project_name,
            "project_slug": project.project_slug,
            "workspace_initialized_at": datetime.now(timezone.utc).isoformat(),
        }

        # 7. Create build session record
        session = WebsiteBuildSession(
            project_id=project_id,
            owner_id=owner_id_clean,
            status=WebsiteBuildSessionStatus.CREATED,
            build_version=next_version,
            build_metadata=snapshot_metadata,
        )
        db.add(session)
        await db.flush()

        # 8. Create PRD_SNAPSHOT artifact record
        artifact = WebsiteBuildArtifact(
            build_session_id=session.id,
            project_id=project_id,
            artifact_type=WebsiteBuildArtifactType.PRD_SNAPSHOT,
            artifact_name=f"PRD Snapshot v{prd.version}",
            artifact_version=1,
            content_reference=f"prd:{prd.id}:v{prd.version}",
            artifact_metadata={
                "prd_title": prd.title,
                "executive_summary": prd.executive_summary,
                "sitemap": prd.sitemap,
                "goals": prd.goals,
            },
        )
        db.add(artifact)
        await db.flush()
        await db.refresh(session)

        # Audit successful creation
        await cls._audit(
            db=db,
            event_name="build_session_created",
            status=AgentRunStatus.COMPLETED,
            owner_id=owner_id_clean,
            details={
                "session_id": str(session.id),
                "project_id": str(project_id),
                "build_version": session.build_version,
                "approved_prd_id": str(prd.id),
                "approved_prd_version": prd.version,
            },
            result="success",
        )

        return session, True

    @classmethod
    async def get_build_session(
        cls,
        db: AsyncSession,
        session_id: uuid.UUID,
        owner_id: str,
    ) -> WebsiteBuildSessionDetailResponse:
        """Retrieve build session with artifacts and project metadata."""
        owner_id_clean = owner_id.lower().strip()

        stmt = (
            select(WebsiteBuildSession)
            .where(WebsiteBuildSession.id == session_id)
            .options(
                selectinload(WebsiteBuildSession.project),
                selectinload(WebsiteBuildSession.artifacts),
            )
        )
        session = (await db.scalars(stmt)).first()

        if session is None:
            raise BuildSessionNotFoundError(f"Build session '{session_id}' not found.")

        if session.owner_id.lower().strip() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="build_session_accessed",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"session_id": str(session_id), "reason": "ownership_mismatch"},
                result="forbidden",
            )
            raise BuildSessionOwnershipError(f"Access denied to build session '{session_id}'.")

        await cls._audit(
            db=db,
            event_name="build_session_accessed",
            status=AgentRunStatus.COMPLETED,
            owner_id=owner_id_clean,
            details={"session_id": str(session_id)},
            result="success",
        )

        project = session.project
        meta = session.build_metadata or {}

        prd_summary = {
            "approved_prd_id": meta.get("approved_prd_id"),
            "approved_prd_version": meta.get("approved_prd_version"),
            "approved_by": meta.get("approved_by"),
            "approved_at": meta.get("approved_at"),
        }

        return WebsiteBuildSessionDetailResponse(
            id=session.id,
            project_id=session.project_id,
            owner_id=session.owner_id,
            status=session.status,
            build_version=session.build_version,
            started_at=session.started_at,
            completed_at=session.completed_at,
            failure_reason=session.failure_reason,
            metadata=session.build_metadata,
            created_at=session.created_at,
            updated_at=session.updated_at,
            artifacts=[
                WebsiteBuildArtifactResponse(
                    id=a.id,
                    build_session_id=a.build_session_id,
                    project_id=a.project_id,
                    artifact_type=a.artifact_type,
                    artifact_name=a.artifact_name,
                    artifact_version=a.artifact_version,
                    content_reference=a.content_reference,
                    metadata=a.artifact_metadata,
                    created_at=a.created_at,
                    updated_at=a.updated_at,
                )
                for a in session.artifacts
            ],
            project_name=project.project_name if project else None,
            project_slug=project.project_slug if project else None,
            project_status=project.project_status.value if project else None,
            approved_prd_id=project.approved_prd_id if project else None,
            approved_prd_version=project.prd_version if project else None,
            prd_summary=prd_summary,
        )

    @classmethod
    async def list_build_sessions_for_project(
        cls,
        db: AsyncSession,
        project_id: uuid.UUID,
        owner_id: str,
    ) -> WebsiteBuildSessionListResponse:
        """List all build sessions for a project with counts."""
        owner_id_clean = owner_id.lower().strip()

        # Check project ownership
        proj_stmt = select(Project).where(Project.id == project_id)
        project = (await db.scalars(proj_stmt)).first()

        if project is None:
            raise BuildSessionProjectIneligibleError(f"Project '{project_id}' not found.")

        if project.owner_id.lower().strip() != owner_id_clean:
            raise BuildSessionOwnershipError(f"Access denied to project '{project_id}'.")

        stmt = (
            select(WebsiteBuildSession)
            .where(
                WebsiteBuildSession.project_id == project_id,
                WebsiteBuildSession.owner_id == owner_id_clean,
            )
            .order_by(desc(WebsiteBuildSession.build_version))
        )
        sessions = list((await db.scalars(stmt)).all())

        total = len(sessions)
        active_count = sum(1 for s in sessions if s.status in ACTIVE_BUILD_STATUSES)
        completed_count = sum(1 for s in sessions if s.status == WebsiteBuildSessionStatus.COMPLETED)
        failed_count = sum(1 for s in sessions if s.status == WebsiteBuildSessionStatus.FAILED)

        return WebsiteBuildSessionListResponse(
            items=[
                WebsiteBuildSessionResponse(
                    id=s.id,
                    project_id=s.project_id,
                    owner_id=s.owner_id,
                    status=s.status,
                    build_version=s.build_version,
                    started_at=s.started_at,
                    completed_at=s.completed_at,
                    failure_reason=s.failure_reason,
                    metadata=s.build_metadata,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                )
                for s in sessions
            ],
            total=total,
            active_count=active_count,
            completed_count=completed_count,
            failed_count=failed_count,
        )

    @classmethod
    async def transition_session_status(
        cls,
        db: AsyncSession,
        session_id: uuid.UUID,
        owner_id: str,
        target_status: WebsiteBuildSessionStatus,
        reason_or_notes: Optional[str] = None,
    ) -> WebsiteBuildSession:
        """
        Safely transition a build session state adhering strictly to the state machine.
        """
        owner_id_clean = owner_id.lower().strip()

        stmt = select(WebsiteBuildSession).where(WebsiteBuildSession.id == session_id)
        session = (await db.scalars(stmt)).first()

        if session is None:
            raise BuildSessionNotFoundError(f"Build session '{session_id}' not found.")

        if session.owner_id.lower().strip() != owner_id_clean:
            await cls._audit(
                db=db,
                event_name="build_session_status_transition_blocked",
                status=AgentRunStatus.FAILED,
                owner_id=owner_id_clean,
                details={"session_id": str(session_id), "reason": "ownership_mismatch"},
                result="forbidden",
            )
            raise BuildSessionOwnershipError(f"Access denied to build session '{session_id}'.")

        current_status = session.status

        # Check if already in terminal state
        if current_status in TERMINAL_BUILD_STATUSES:
            raise BuildSessionTerminalStateError(
                f"Build session '{session_id}' is in terminal state '{current_status.value}' and cannot be transitioned."
            )

        # Validate transition
        allowed_targets = VALID_STATE_TRANSITIONS.get(current_status, set())
        if target_status not in allowed_targets:
            raise BuildSessionInvalidStateTransitionError(
                f"Cannot transition build session from '{current_status.value}' to '{target_status.value}'. "
                f"Allowed transitions from '{current_status.value}': {[s.value for s in allowed_targets]}"
            )

        now = datetime.now(timezone.utc)
        session.status = target_status

        # Timestamp tracking
        if target_status == WebsiteBuildSessionStatus.IN_PROGRESS and session.started_at is None:
            session.started_at = now
        elif target_status in TERMINAL_BUILD_STATUSES:
            session.completed_at = now
            if target_status == WebsiteBuildSessionStatus.FAILED and reason_or_notes:
                session.failure_reason = reason_or_notes

        # Audit event mapping
        audit_event_map = {
            WebsiteBuildSessionStatus.PLANNED: "build_session_planned",
            WebsiteBuildSessionStatus.READY: "build_session_ready",
            WebsiteBuildSessionStatus.PAUSED: "build_session_paused",
            WebsiteBuildSessionStatus.CANCELLED: "build_session_cancelled",
            WebsiteBuildSessionStatus.FAILED: "build_session_failed",
            WebsiteBuildSessionStatus.COMPLETED: "build_session_completed",
            WebsiteBuildSessionStatus.IN_PROGRESS: "build_session_in_progress",
        }
        event_name = audit_event_map.get(target_status, "build_session_transitioned")

        if reason_or_notes:
            meta = dict(session.build_metadata)
            meta[f"{target_status.value}_note"] = reason_or_notes
            session.build_metadata = meta

        await db.flush()
        await db.refresh(session)

        await cls._audit(
            db=db,
            event_name=event_name,
            status=AgentRunStatus.COMPLETED,
            owner_id=owner_id_clean,
            details={
                "session_id": str(session_id),
                "from_status": current_status.value,
                "to_status": target_status.value,
                "note": reason_or_notes,
            },
            result="success",
        )

        return session
