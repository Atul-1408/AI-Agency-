"""
Phase 4 — Follow-up Sequence and Step Database Models.

Entities defined:
- FollowUpSequence: State machine tracking follow-up cadence for a sent outreach message.
- FollowUpStep: Individual scheduled step in an ordered sequence.

Enums:
- FollowUpSequenceStatus: ACTIVE, PAUSED, STOPPED, COMPLETED
- FollowUpStepStatus: PENDING, READY, SENT, SKIPPED, CANCELLED, FAILED
- FollowUpStopReason: REPLIED, OWNER_STOPPED, SUPPRESSED, BOUNCE, MAX_STEPS_REACHED,
                      SAFETY_BLOCKED, GMAIL_DISCONNECTED, OTHER
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from models import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from models import Lead
    from models.outreach import OutreachDraft, OutreachMessage


# ── Enums ─────────────────────────────────────────────────────────────────────

class FollowUpSequenceStatus(str, enum.Enum):
    """Lifecycle states for a follow-up sequence."""
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class FollowUpStepStatus(str, enum.Enum):
    """Lifecycle states for an individual follow-up step."""
    PENDING = "pending"
    READY = "ready"
    SENT = "sent"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    FAILED = "failed"


class FollowUpStopReason(str, enum.Enum):
    """Explicit reasons why a follow-up sequence was terminated."""
    REPLIED = "replied"
    OWNER_STOPPED = "owner_stopped"
    SUPPRESSED = "suppressed"
    BOUNCE = "bounce"
    MAX_STEPS_REACHED = "max_steps_reached"
    SAFETY_BLOCKED = "safety_blocked"
    GMAIL_DISCONNECTED = "gmail_disconnected"
    OTHER = "other"


# ── Models ────────────────────────────────────────────────────────────────────

class FollowUpSequence(UUIDPKMixin, TimestampMixin, Base):
    """
    Automated cadence tracker for follow-up emails tied to a sent outreach message.
    
    Guarantees:
    - Belongs to exactly one Lead.
    - Associated with an original OutreachMessage and original OutreachDraft.
    - Status transitions strictly controlled by FollowUpService.
    - Automatically stops upon reply detection or suppression.
    """
    __tablename__ = "follow_up_sequences"
    __table_args__ = (
        Index("ix_followup_seq_lead_status", "lead_id", "status"),
        Index("ix_followup_seq_status_next_action", "status", "next_action_at"),
        Index("ix_followup_seq_orig_msg", "original_message_id"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    outreach_draft_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outreach_drafts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    original_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outreach_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    status: Mapped[FollowUpSequenceStatus] = mapped_column(
        Enum(FollowUpSequenceStatus, name="follow_up_sequence_status", native_enum=False),
        default=FollowUpSequenceStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    max_steps: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    next_action_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    stopped_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stop_reason: Mapped[Optional[FollowUpStopReason]] = mapped_column(
        Enum(FollowUpStopReason, name="follow_up_stop_reason", native_enum=False),
        nullable=True,
    )

    # Relationships
    lead: Mapped["Lead"] = relationship(lazy="select")
    draft: Mapped[Optional["OutreachDraft"]] = relationship(lazy="select")
    original_message: Mapped[Optional["OutreachMessage"]] = relationship(lazy="select")
    steps: Mapped[List["FollowUpStep"]] = relationship(
        back_populates="sequence",
        cascade="all, delete-orphan",
        order_by="FollowUpStep.step_number",
        lazy="select",
    )


class FollowUpStep(UUIDPKMixin, TimestampMixin, Base):
    """
    An individual step in a follow-up sequence.
    
    Guarantees:
    - Ordered by step_number.
    - Explicit delay_hours relative to initial send.
    - Holds scheduled_at, executed_at, and optional follow-up draft_id.
    """
    __tablename__ = "follow_up_steps"
    __table_args__ = (
        Index("ix_followup_step_seq_number", "sequence_id", "step_number", unique=True),
        Index("ix_followup_step_status_scheduled", "status", "scheduled_at"),
    )

    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("follow_up_sequences.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    delay_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[FollowUpStepStatus] = mapped_column(
        Enum(FollowUpStepStatus, name="follow_up_step_status", native_enum=False),
        default=FollowUpStepStatus.PENDING,
        nullable=False,
        index=True,
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    executed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    draft_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outreach_drafts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relationships
    sequence: Mapped["FollowUpSequence"] = relationship(back_populates="steps")
    draft: Mapped[Optional["OutreachDraft"]] = relationship(lazy="select")


class InboundMessage(UUIDPKMixin, TimestampMixin, Base):
    """
    Audit record of an inbound prospect message/reply detected via Gmail.
    
    Guarantees:
    - Unique constraint on gmail_message_id ensures idempotency and duplicate prevention.
    - Minimal stored data: snippet and metadata only (no full email bodies).
    - Never stores OAuth tokens or credentials.
    - Anchored to matched OutreachMessage, Lead, and FollowUpSequence where applicable.
    """
    __tablename__ = "inbound_messages"
    __table_args__ = (
        Index("ix_inbound_msg_thread", "gmail_thread_id"),
        Index("ix_inbound_msg_sender", "sender_email"),
        Index("ix_inbound_msg_lead", "matched_lead_id"),
        Index("ix_inbound_msg_seq", "matched_sequence_id"),
    )

    gmail_message_id: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    gmail_thread_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    sender_email: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    recipient_email: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    subject: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    snippet: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    matched_outreach_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outreach_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    matched_lead_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    matched_sequence_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("follow_up_sequences.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    processing_status: Mapped[str] = mapped_column(
        String(50), default="PROCESSED", nullable=False, index=True
    )

    # Relationships
    lead: Mapped[Optional["Lead"]] = relationship(lazy="select")
    outreach_message: Mapped[Optional["OutreachMessage"]] = relationship(lazy="select")
    sequence: Mapped[Optional["FollowUpSequence"]] = relationship(lazy="select")
