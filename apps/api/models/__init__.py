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

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
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


class LeadStatus(str, enum.Enum):
    """Lifecycle status of a business lead."""
    DISCOVERED = "discovered"       # Found via discovery provider
    RESEARCHING = "researching"     # Currently being audited
    RESEARCHED = "researched"       # Technical audit completed
    QUALIFIED = "qualified"         # Opportunity score >= 60
    LOW_PRIORITY = "low_priority"   # Opportunity score 30-59
    DISQUALIFIED = "disqualified"   # Score < 30 or suppression match
    APPROVED = "approved"           # Owner approved for outreach
    REJECTED = "rejected"           # Owner rejected


class EmailVerificationStatus(str, enum.Enum):
    """Honest verification states for discovered business email."""
    UNVERIFIED = "unverified"
    SYNTAX_VALID = "syntax_valid"
    MX_VERIFIED = "mx_verified"
    UNREACHABLE = "unreachable"


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


# ── Phase 2 Models ────────────────────────────────────────────────────────────

class Lead(UUIDPKMixin, TimestampMixin, Base):
    """
    Business prospect discovered and qualified for web agency services.
    Every lead retains full provenance and an objective opportunity score.
    """
    __tablename__ = "leads"

    company_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(255), unique=False, nullable=False, index=True)
    website_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    google_place_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    email_verification_status: Mapped[EmailVerificationStatus] = mapped_column(
        Enum(EmailVerificationStatus, name="email_verification_status", native_enum=False),
        default=EmailVerificationStatus.UNVERIFIED,
        nullable=False,
    )
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    industry: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    qualification_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus, name="lead_status", native_enum=False),
        default=LeadStatus.DISCOVERED,
        nullable=False,
        index=True,
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Source provenance
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_query: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Relationships
    research: Mapped[Optional["LeadResearch"]] = relationship(
        back_populates="lead",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="select",
    )
    outreach_drafts: Mapped[list["OutreachDraft"]] = relationship(
        "OutreachDraft",
        back_populates="lead",
        cascade="all, delete-orphan",
        lazy="select",
    )
    outreach_messages: Mapped[list["OutreachMessage"]] = relationship(
        "OutreachMessage",
        back_populates="lead",
        cascade="all, delete-orphan",
        lazy="select",
    )
    send_attempts: Mapped[list["SendAttempt"]] = relationship(
        "SendAttempt",
        back_populates="lead",
        cascade="all, delete-orphan",
        lazy="select",
    )


class LeadResearch(UUIDPKMixin, TimestampMixin, Base):
    """
    Objective technical audit and observable signals for a lead.
    Zero subjective AI claims — strictly recorded factual technical indicators.
    """
    __tablename__ = "lead_research"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    has_website: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_responsive: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    has_ssl: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    load_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    copyright_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    tech_stack: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    audit_findings: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    research_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    lead: Mapped["Lead"] = relationship(back_populates="research")


# ── Phase 3 Models ────────────────────────────────────────────────────────────

from models.outreach import (
    CircuitBreakerState,
    DeliveryEvent,
    DeliveryEventType,
    GmailAccount,
    GmailConnectionStatus,
    OutreachDraft,
    OutreachDraftStatus,
    OutreachMessage,
    OutreachMessageStatus,
    SendAttempt,
    SendAttemptResult,
    SuppressionReason,
    SuppressionRecord,
)

__all__ = [
    # Mixins
    "TimestampMixin",
    "UUIDPKMixin",
    # Phase 1
    "AgentRun",
    "AgentRunStatus",
    "ApprovalRequest",
    "ApprovalStatus",
    # Phase 2
    "Lead",
    "LeadStatus",
    "EmailVerificationStatus",
    "LeadResearch",
    # Phase 3
    "CircuitBreakerState",
    "OutreachDraft",
    "OutreachDraftStatus",
    "GmailAccount",
    "GmailConnectionStatus",
    "OutreachMessage",
    "OutreachMessageStatus",
    "SendAttempt",
    "SendAttemptResult",
    "SuppressionRecord",
    "SuppressionReason",
    "DeliveryEvent",
    "DeliveryEventType",
]

