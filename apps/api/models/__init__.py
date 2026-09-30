"""
Phase 1 database models.

ONLY Phase 1 entities are defined here.
Future phases add their own models when approved:
  - Phase 2: Lead, LeadResearch
  - Phase 3: OutreachThread, OutreachMessage
  - Phase 5: ClientConversation, PRD
  - Phase 6: Project, GeneratedFile
  - Phase 8: Deployment
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from core.database import Base


# ── Mixins ────────────────────────────────────────────────────────────────────

class TimestampMixin:
    """Adds created_at and updated_at to any model."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDPKMixin:
    """UUID primary key."""
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True
    )


# ── Enums ─────────────────────────────────────────────────────────────────────

class AgentRunStatus(str, enum.Enum):
    """Lifecycle states for an agent job execution."""
    PENDING = "pending"       # Created, not yet picked up by worker
    RUNNING = "running"       # Worker has started processing
    COMPLETED = "completed"   # Finished successfully
    FAILED = "failed"         # Encountered an unrecoverable error
    CANCELLED = "cancelled"   # Explicitly cancelled by owner


class ApprovalStatus(str, enum.Enum):
    """Owner decision on a human-approval-gate request."""
    PENDING = "pending"     # Awaiting owner decision
    APPROVED = "approved"   # Owner approved — agent may proceed
    REJECTED = "rejected"   # Owner rejected — agent must stop


# ── Phase 1 Models ────────────────────────────────────────────────────────────

class AgentRun(UUIDPKMixin, TimestampMixin, Base):
    """
    Immutable audit record for every agent execution.
    One row per agent job invocation.

    This is the primary observability table for Phase 1.
    All agent activity is traceable here.
    """
    __tablename__ = "agent_runs"

    # Which agent ran
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Link to the ARQ job (if queued via ARQ)
    job_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # Lifecycle
    status: Mapped[AgentRunStatus] = mapped_column(
        Enum(AgentRunStatus, name="agent_run_status"),
        default=AgentRunStatus.PENDING,
        nullable=False,
        index=True,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Data
    input_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    output_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Cost tracking (tokens used when AI calls are made in Phase 9+)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships to approval requests created during this run
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(
        back_populates="agent_run",
        cascade="all, delete-orphan",
        lazy="select",
    )


class ApprovalRequest(UUIDPKMixin, TimestampMixin, Base):
    """
    Human-in-the-loop approval gate.

    When an agent wants to take a consequential action (send email,
    deploy website, etc.) it creates an ApprovalRequest and pauses.
    The owner approves or rejects via the dashboard.
    The agent then proceeds or aborts.

    This table is the primary mechanism enforcing the
    'human remains in control' requirement from the MASTER SPEC.
    """
    __tablename__ = "approval_requests"

    # What action is being requested
    action_type: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
        # Examples: "send_email", "deploy_website", "qualify_lead_batch"
    )

    # Full context for the owner to make a decision
    payload: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    # Owner decision
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="approval_status"),
        default=ApprovalStatus.PENDING,
        nullable=False,
        index=True,
    )
    owner_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Back-link to the agent run that created this request
    agent_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent_run: Mapped[Optional["AgentRun"]] = relationship(
        back_populates="approval_requests"
    )
