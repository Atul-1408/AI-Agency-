"""
Phase 3 — Outreach Agent Database Models.

Entities defined here:
- OutreachDraft: Factual personalized email drafts requiring Gate 2 human approval.
- GmailAccount: Connected Google account credentials (AES-GCM encrypted refresh token).
- OutreachMessage: Immutable audit record of emails submitted to Gmail API.
- SendAttempt: Detailed audit log of every send attempt (success, blocked, failed).
- SuppressionRecord: Email and domain level suppression lists (opt-out, bounce, block).
- DeliveryEvent: Delivery status updates and telemetry events.

IMPORTANT:
- No Gmail OAuth, API, or sending logic is implemented in Stage 3.1.
- Tokens must remain encrypted at all times; never store or expose plaintext.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.types import JSON

from core.database import Base
from models import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from models import Lead
    from models.follow_up import FollowUpSequence, FollowUpStep


# ── Enums ─────────────────────────────────────────────────────────────────────

class OutreachDraftStatus(str, enum.Enum):
    """Lifecycle states for an outreach email draft."""
    DRAFTED = "drafted"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"
    SUPPRESSED = "suppressed"


class CircuitBreakerState(str, enum.Enum):
    """Operational states of the outreach delivery circuit breaker."""
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    THROTTLED = "THROTTLED"
    PAUSED = "PAUSED"


class GmailConnectionStatus(str, enum.Enum):
    """Health & connection states of the owner's linked Gmail account."""
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class OutreachMessageStatus(str, enum.Enum):
    """Status of an outreach message recorded after submission."""
    SENT = "sent"
    FAILED = "failed"
    BOUNCED = "bounced"


class SendAttemptResult(str, enum.Enum):
    """Audit result of an attempted email send execution."""
    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"


class SuppressionReason(str, enum.Enum):
    """Root cause justification for suppressing an email or domain."""
    OPT_OUT = "opt_out"
    HARD_BOUNCE = "hard_bounce"
    SPAM_COMPLAINT = "spam_complaint"
    MANUAL_BLOCK = "manual_block"


class DeliveryEventType(str, enum.Enum):
    """Granular delivery event category."""
    SENT = "sent"
    BOUNCED = "bounced"
    FAILED = "failed"


# ── Models ────────────────────────────────────────────────────────────────────

class OutreachDraft(UUIDPKMixin, TimestampMixin, Base):
    """
    Factual personalized email draft generated for a qualified, owner-approved lead.
    Must pass Gate 2 human approval before any safety checks or dispatch can occur.
    """
    __tablename__ = "outreach_drafts"

    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[OutreachDraftStatus] = mapped_column(
        Enum(OutreachDraftStatus, name="outreach_draft_status", native_enum=False),
        default=OutreachDraftStatus.DRAFTED,
        nullable=False,
        index=True,
    )

    # Gate 2 Human Approval fields
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Follow-up Sequence association (if this draft is part of a follow-up sequence)
    follow_up_sequence_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("follow_up_sequences.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        index=True,
    )
    follow_up_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("follow_up_steps.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        unique=True,
        index=True,
    )

    # Relationships
    lead: Mapped["Lead"] = relationship(back_populates="outreach_drafts")
    messages: Mapped[List["OutreachMessage"]] = relationship(
        back_populates="draft",
        lazy="select",
    )
    send_attempts: Mapped[List["SendAttempt"]] = relationship(
        back_populates="draft",
        lazy="select",
    )
    follow_up_sequence: Mapped[Optional["FollowUpSequence"]] = relationship(
        foreign_keys=[follow_up_sequence_id],
        lazy="select",
    )
    follow_up_step: Mapped[Optional["FollowUpStep"]] = relationship(
        foreign_keys=[follow_up_step_id],
        lazy="select",
    )


class GmailAccount(UUIDPKMixin, TimestampMixin, Base):
    """
    Connected Google Workspace / Gmail account credentials for the owner.
    
    SECURITY NOTE:
    Stage 3.1 creates the database schema only.
    Stage 3.2/3.3 will implement AES-GCM encryption and OAuth2 flows.
    The refresh token is strictly encrypted before persistence and is NEVER
    exposed in plain text or serialized in API response schemas.
    """
    __tablename__ = "gmail_accounts"

    owner_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, default="owner"
    )
    google_email: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    encrypted_refresh_token: Mapped[str] = mapped_column(
        Text, nullable=False
    )
    token_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_token_refresh_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    connection_status: Mapped[GmailConnectionStatus] = mapped_column(
        Enum(GmailConnectionStatus, name="gmail_connection_status", native_enum=False),
        default=GmailConnectionStatus.DISCONNECTED,
        nullable=False,
        index=True,
    )
    last_health_check: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error_code: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True
    )


class OutreachMessage(UUIDPKMixin, TimestampMixin, Base):
    """
    Audit record of an outreach email submitted to the Gmail API.
    Retains Gmail Message ID and Thread ID for conversation continuity and tracking.
    """
    __tablename__ = "outreach_messages"

    draft_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outreach_drafts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    gmail_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    gmail_thread_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[OutreachMessageStatus] = mapped_column(
        Enum(OutreachMessageStatus, name="outreach_message_status", native_enum=False),
        default=OutreachMessageStatus.SENT,
        nullable=False,
        index=True,
    )

    # Relationships
    lead: Mapped["Lead"] = relationship(back_populates="outreach_messages")
    draft: Mapped[Optional["OutreachDraft"]] = relationship(back_populates="messages")
    delivery_events: Mapped[List["DeliveryEvent"]] = relationship(
        back_populates="outreach_message",
        cascade="all, delete-orphan",
        lazy="select",
    )


class SendAttempt(UUIDPKMixin, Base):
    """
    Auditable log of every send attempt executed by the safety controller or dispatch engine.
    Records successful dispatches as well as safety-blocked (quota, pacing, suppression) or failed attempts.
    """
    __tablename__ = "send_attempts"

    draft_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outreach_drafts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    result: Mapped[SendAttemptResult] = mapped_column(
        Enum(SendAttemptResult, name="send_attempt_result", native_enum=False),
        nullable=False,
        index=True,
    )
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gmail_message_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    gmail_thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    lead: Mapped["Lead"] = relationship(back_populates="send_attempts")
    draft: Mapped[Optional["OutreachDraft"]] = relationship(back_populates="send_attempts")


class SuppressionRecord(UUIDPKMixin, TimestampMixin, Base):
    """
    Suppression registry preventing emails or entire domains from being contacted.
    Protects agency reputation and respects opt-out, bounce, and spam complaint policies.
    """
    __tablename__ = "suppression_records"
    __table_args__ = (
        CheckConstraint(
            "(email IS NOT NULL AND length(email) > 0) OR (domain IS NOT NULL AND length(domain) > 0)",
            name="ck_suppression_target",
        ),
        Index("ix_suppression_email", "email"),
        Index("ix_suppression_domain", "domain"),
    )

    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reason: Mapped[SuppressionReason] = mapped_column(
        Enum(SuppressionReason, name="suppression_reason", native_enum=False),
        nullable=False,
        index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="system")

    @validates("email", "domain")
    def validate_target(self, key: str, value: Optional[str]) -> Optional[str]:
        if value is not None:
            value = value.strip().lower()
            if not value:
                value = None
        return value


class DeliveryEvent(UUIDPKMixin, Base):
    """
    Granular lifecycle event for an outreach message (sent, bounced, failed).
    """
    __tablename__ = "delivery_events"

    outreach_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("outreach_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[DeliveryEventType] = mapped_column(
        Enum(DeliveryEventType, name="delivery_event_type", native_enum=False),
        nullable=False,
        index=True,
    )
    event_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        "metadata", JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationship
    outreach_message: Mapped["OutreachMessage"] = relationship(
        back_populates="delivery_events"
    )


class ConsumedOAuthState(UUIDPKMixin, Base):
    """
    OAuth State Replay Protection Store.
    
    Tracks consumed OAuth state identifiers (jti) to prevent state replay attacks.
    Tokens expire in 10 minutes and can strictly be consumed only once.
    """
    __tablename__ = "consumed_oauth_states"

    jti: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

