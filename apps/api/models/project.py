"""
Phase 5 Stage 5.4 — Project Model and Lifecycle State Foundation.

Entities defined:
- Project: The official human-controlled project record created from an approved PRD.
- ProjectStatus: Lifecycle states for the project (initial: READY_FOR_BUILD).

SECURITY MANDATES:
- Project creation is human-controlled under Gate 4: PRD must be APPROVED by owner.
- An approved PRD can create at most ONE project (enforced via database uniqueness on approved_prd_id).
- owner_id is ALWAYS derived from verified JWT authentication — never from client request body.
- Approved PRD version, approval timestamp, and requirements are immutably snapshotted in phase_metadata.
- Phase 5.4 ONLY establishes the project record and handoff foundation.
- No website builder, GitHub, Vercel, or deployment execution occurs in this stage.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional
import uuid

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from models import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from models import Lead
    from models.client_intelligence import ClientConversation, ClientPRD


# ── Project Lifecycle Status ──────────────────────────────────────────────────

class ProjectStatus(str, enum.Enum):
    """
    Lifecycle states for an AI Web Agency website project.

    Phase 5.4 establishes the initial handoff state:
    - READY_FOR_BUILD: Project record established from approved PRD, ready for Phase 6 handoff.

    Future states (Phase 6, 7, 8) are defined as foundation but transitions are blocked in Phase 5.4:
    - DRAFT: Initial unsubmitted draft (not used for approved PRD flow)
    - IN_BUILD: Phase 6 website generator active
    - QA: Phase 7 automated QA verification
    - READY_FOR_DEPLOYMENT: QA passed, awaiting deployment
    - DEPLOYED: Phase 8 production deployment live
    - COMPLETED: Final project handoff complete
    - CANCELLED: Project explicitly cancelled by owner
    """
    DRAFT                 = "draft"
    READY_FOR_BUILD       = "ready_for_build"
    IN_BUILD              = "in_build"
    QA                    = "qa"
    READY_FOR_DEPLOYMENT  = "ready_for_deployment"
    DEPLOYED              = "deployed"
    COMPLETED             = "completed"
    CANCELLED             = "cancelled"


# ── Project Model ─────────────────────────────────────────────────────────────

class Project(UUIDPKMixin, TimestampMixin, Base):
    """
    Official website project record anchored to an Approved PRD (Gate 4).

    Guarantees:
    - Exactly one Project per approved PRD (enforced via UniqueConstraint on approved_prd_id).
    - Owner isolation: owner_id matches authenticated agency owner.
    - Sourced from verified conversation, lead, and approved PRD version.
    - Preserves deterministic snapshot of requirements in phase_metadata.
    """
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("approved_prd_id", name="uq_projects_approved_prd_id"),
        Index("ix_projects_owner_id", "owner_id"),
        Index("ix_projects_lead_id", "lead_id"),
        Index("ix_projects_conversation_id", "conversation_id"),
        Index("ix_projects_status", "project_status"),
        Index("ix_projects_slug", "project_slug"),
    )

    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    approved_prd_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_prds.id", ondelete="CASCADE"),
        nullable=False,
    )
    prd_version: Mapped[int] = mapped_column(Integer, nullable=False)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    project_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    project_status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status", native_enum=False),
        default=ProjectStatus.READY_FOR_BUILD,
        nullable=False,
    )
    project_source: Mapped[str] = mapped_column(String(50), default="approved_prd", nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    phase_metadata: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Relationships
    lead: Mapped["Lead"] = relationship(lazy="select")
    conversation: Mapped["ClientConversation"] = relationship(lazy="select")
    approved_prd: Mapped["ClientPRD"] = relationship(lazy="select")
