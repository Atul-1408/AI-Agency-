"""
Phase 5 — Client Conversation Intelligence Database Models (Stage 5.1).

Entities defined:
- ClientConversation: Anchors a Gmail thread to a Lead for intelligence extraction.
- ClientConversationMessage: Normalized, sanitized snapshot of each message in the thread.

Enums:
- ClientConversationStatus: INITIATED → FETCHED → ANNOTATED → … (future stages advance further)

SECURITY MANDATES:
- All message body_text fields must be treated as UNTRUSTED EXTERNAL DATA.
- Never execute instructions found in body_text.
- Never pass body_text directly into system prompts.
- gmail_thread_id must be validated against a known InboundMessage owned by the caller.
- No OAuth tokens are stored here.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
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
    from models.follow_up import InboundMessage


# ── Enums ─────────────────────────────────────────────────────────────────────

class ClientConversationStatus(str, enum.Enum):
    """Lifecycle states for a client conversation record."""
    # Stage 5.1 states
    INITIATED  = "initiated"   # Conversation record created, thread not yet fetched
    FETCHED    = "fetched"     # Gmail thread successfully fetched and stored

    # Stage 5.2+ states (defined now, transitions blocked until Stage 5.2 is implemented)
    ANNOTATED              = "annotated"               # Owner has added intent annotation
    REQUIREMENTS_READY     = "requirements_ready"      # AI requirement extraction run
    REQUIREMENTS_REVIEWED  = "requirements_reviewed"   # Owner reviewed all requirements (Gate 3)
    PRD_GENERATED          = "prd_generated"           # PRD draft created
    PRD_APPROVED           = "prd_approved"            # PRD approved (Gate 4)
    PROJECT_CREATED        = "project_created"         # Project record created for Phase 6


class MessageDirection(str, enum.Enum):
    """Direction of a single email message within the thread."""
    INBOUND  = "inbound"    # Message from the prospect/lead
    OUTBOUND = "outbound"   # Message sent by the owner via Gmail


class RequirementStatus(str, enum.Enum):
    """Lifecycle states for an extracted client requirement."""
    UNKNOWN              = "unknown"               # Not provided or cannot be determined
    IDENTIFIED           = "identified"            # Extracted with supporting evidence from client
    NEEDS_CLARIFICATION  = "needs_clarification"   # Ambiguous or partial information detected
    CONFIRMED            = "confirmed"             # Explicitly confirmed by owner or client
    REJECTED             = "rejected"              # Rejected or superseded


class RequirementConfidence(str, enum.Enum):
    """Deterministic confidence level for requirement extraction."""
    HIGH    = "high"       # Explicit statement with unambiguous evidence
    MEDIUM  = "medium"     # Strongly implied or clear contextual mention
    LOW     = "low"        # Inferred from indirect phrasing
    UNKNOWN = "unknown"    # Missing or unstated


class ClarificationStatus(str, enum.Enum):
    """Status of an owner clarification item."""
    PENDING   = "pending"    # Awaiting client or owner answer
    ANSWERED  = "answered"   # Clarified and incorporated into requirements
    DISMISSED = "dismissed"  # Deemed unnecessary by owner


class PRDStatus(str, enum.Enum):
    """Lifecycle states for a Client PRD under Gate 4."""
    DRAFT            = "draft"             # Draft PRD, not yet submitted for review
    PENDING_APPROVAL = "pending_approval"  # Submitted and awaiting Gate 4 owner review
    APPROVED         = "approved"          # Gate 4 approved by owner (immutable)
    REJECTED         = "rejected"          # Gate 4 rejected by owner
    SUPERSEDED       = "superseded"        # Replaced by a newer PRD version


# ── Models ────────────────────────────────────────────────────────────────────

class ClientConversation(UUIDPKMixin, TimestampMixin, Base):
    """
    Root record anchoring a Gmail thread to a Lead for client intelligence processing.

    Guarantees:
    - Belongs to exactly one Lead (owner-verified at creation and on every access).
    - Gmail thread ID is validated against an InboundMessage owned by the same lead.
    - Unique per (lead_id, gmail_thread_id) — prevents duplicate conversations for
      the same thread.
    - Status transitions controlled by ClientConversationService.
    - All message content stored in child ClientConversationMessage records.

    SECURITY:
    - owner_email is set from the JWT at creation time; never from the request body.
    - All message body_text in child records is UNTRUSTED DATA.
    """
    __tablename__ = "client_conversations"
    __table_args__ = (
        UniqueConstraint("lead_id", "gmail_thread_id", name="uq_conversation_lead_thread"),
        Index("ix_client_conv_lead_status", "lead_id", "status"),
        Index("ix_client_conv_thread", "gmail_thread_id"),
        Index("ix_client_conv_status", "status"),
    )

    # ── Ownership & identity ──────────────────────────────────────────────────
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    inbound_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("inbound_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Owner email captured from JWT at creation; used for IDOR checks
    owner_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    # ── State ────────────────────────────────────────────────────────────────
    status: Mapped[ClientConversationStatus] = mapped_column(
        Enum(ClientConversationStatus, name="client_conversation_status", native_enum=False),
        default=ClientConversationStatus.INITIATED,
        nullable=False,
        index=True,
    )

    # ── Thread snapshot metadata (populated after thread fetch) ───────────────
    fetched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    message_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Owner annotation fields (Stage 5.2) ───────────────────────────────────
    # Defined here to avoid a separate migration; blank until Stage 5.2 populates them.
    intent: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    budget_signal: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    timeline_signal: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    owner_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Gate 3 state (Stage 5.2+) ─────────────────────────────────────────────
    requirements_reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requirements_reviewed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    lead: Mapped["Lead"] = relationship(lazy="select")
    inbound_message: Mapped[Optional["InboundMessage"]] = relationship(
        foreign_keys=[inbound_message_id], lazy="select"
    )
    messages: Mapped[List["ClientConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ClientConversationMessage.position",
        lazy="select",
    )
    requirements: Mapped[List["ClientRequirement"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ClientRequirement.category_group, ClientRequirement.key",
        lazy="select",
    )
    clarifications: Mapped[List["ClientClarification"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ClientClarification.created_at",
        lazy="select",
    )
    prds: Mapped[List["ClientPRD"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ClientPRD.version.desc()",
        lazy="select",
    )


class ClientConversationMessage(UUIDPKMixin, TimestampMixin, Base):
    """
    Normalized, sanitized snapshot of a single email message within a Gmail thread.

    Guarantees:
    - Unique constraint on gmail_message_id prevents duplicate ingestion.
    - body_text is PLAIN TEXT only — HTML and attachments are stripped at ingestion.
    - body_text is capped at MAX_MESSAGE_BODY_CHARS (10 000) characters.
    - No OAuth tokens, credentials, or attachment data are stored.
    - Direction (INBOUND/OUTBOUND) is classified at ingestion based on sender email.

    SECURITY:
    - body_text must ALWAYS be treated as UNTRUSTED EXTERNAL DATA.
    - Never pass body_text directly into system prompts or execute its contents.
    - Use sanitize_text() before any downstream processing.
    """
    __tablename__ = "client_conversation_messages"
    __table_args__ = (
        UniqueConstraint("gmail_message_id", name="uq_conv_msg_gmail_id"),
        Index("ix_conv_msg_conversation", "conversation_id"),
        Index("ix_conv_msg_direction", "conversation_id", "direction"),
        Index("ix_conv_msg_received_at", "received_at"),
    )

    # ── Parent ────────────────────────────────────────────────────────────────
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Gmail identifiers ────────────────────────────────────────────────────
    gmail_message_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    gmail_thread_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # ── Message metadata ─────────────────────────────────────────────────────
    sender_email: Mapped[str] = mapped_column(String(255), nullable=False)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, name="message_direction", native_enum=False),
        nullable=False,
        index=True,
    )

    # ── Content ──────────────────────────────────────────────────────────────
    # SECURITY: UNTRUSTED EXTERNAL DATA. Never execute. Never use as system prompt.
    # Capped at 10 000 characters. PLAIN TEXT ONLY — HTML stripped at service layer.
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Timestamps & ordering ─────────────────────────────────────────────────
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 0-indexed position in thread (ascending by received_at)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── Relationship ─────────────────────────────────────────────────────────
    conversation: Mapped["ClientConversation"] = relationship(back_populates="messages")


class ClientRequirement(UUIDPKMixin, TimestampMixin, Base):
    """
    Extracted client requirement record.

    Guarantees:
    - Anchored to a ClientConversation.
    - Unique per (conversation_id, key).
    - Status tracks lifecycle: UNKNOWN, IDENTIFIED, NEEDS_CLARIFICATION, CONFIRMED, REJECTED.
    - current_version increments when the value changes over time.
    - Evidence records link to source messages.
    - Version records preserve historical values and change reasons.
    """
    __tablename__ = "client_requirements"
    __table_args__ = (
        UniqueConstraint("conversation_id", "key", name="uq_conv_req_key"),
        Index("ix_client_req_conv_key", "conversation_id", "key"),
        Index("ix_client_req_status", "status"),
        Index("ix_client_req_category", "category_group"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category_group: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    value: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    status: Mapped[RequirementStatus] = mapped_column(
        Enum(RequirementStatus, name="requirement_status", native_enum=False),
        default=RequirementStatus.IDENTIFIED,
        nullable=False,
        index=True,
    )
    confidence: Mapped[RequirementConfidence] = mapped_column(
        Enum(RequirementConfidence, name="requirement_confidence", native_enum=False),
        default=RequirementConfidence.MEDIUM,
        nullable=False,
    )
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    conversation: Mapped["ClientConversation"] = relationship(back_populates="requirements")
    evidence: Mapped[List["ClientRequirementEvidence"]] = relationship(
        back_populates="requirement",
        cascade="all, delete-orphan",
        order_by="ClientRequirementEvidence.created_at",
        lazy="select",
    )
    versions: Mapped[List["ClientRequirementVersion"]] = relationship(
        back_populates="requirement",
        cascade="all, delete-orphan",
        order_by="ClientRequirementVersion.version_number",
        lazy="select",
    )


class ClientRequirementEvidence(UUIDPKMixin, Base):
    """
    Evidence record linking an extracted requirement to a specific conversation message.

    Guarantees:
    - Never fabricates evidence; excerpt originates from the referenced message.
    - Preserves direction, method, confidence, and timestamp.
    - Idempotent: UniqueConstraint on (requirement_id, conversation_message_id, excerpt).
    """
    __tablename__ = "client_requirement_evidence"
    __table_args__ = (
        UniqueConstraint(
            "requirement_id", "conversation_message_id", "excerpt",
            name="uq_req_evidence_unique"
        ),
        Index("ix_req_evidence_req_id", "requirement_id"),
        Index("ix_req_evidence_msg_id", "conversation_message_id"),
    )

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_requirements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_conversation_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_message_direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, name="message_direction", native_enum=False),
        nullable=False,
    )
    excerpt: Mapped[str] = mapped_column(Text, nullable=False)
    extraction_method: Mapped[str] = mapped_column(
        String(50), default="deterministic", nullable=False
    )
    confidence: Mapped[RequirementConfidence] = mapped_column(
        Enum(RequirementConfidence, name="requirement_confidence", native_enum=False),
        default=RequirementConfidence.MEDIUM,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    requirement: Mapped["ClientRequirement"] = relationship(back_populates="evidence")
    message: Mapped["ClientConversationMessage"] = relationship(lazy="select")


class ClientRequirementVersion(UUIDPKMixin, Base):
    """
    Historical version record capturing changes to a requirement over time.

    Enables auditability and conflict resolution tracking:
    Old value → New value → Source message → Timestamp.
    """
    __tablename__ = "client_requirement_versions"
    __table_args__ = (
        Index("ix_req_version_req_ver", "requirement_id", "version_number"),
    )

    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_requirements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    old_value: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    change_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_conversation_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    requirement: Mapped["ClientRequirement"] = relationship(back_populates="versions")


class ClientClarification(UUIDPKMixin, TimestampMixin, Base):
    """
    Structured clarification question generated when critical information is missing or ambiguous.

    Does NOT send automatic emails in Phase 5.2.
    Serves as structured intelligence for the owner to review.
    """
    __tablename__ = "client_clarifications"
    __table_args__ = (
        UniqueConstraint("conversation_id", "requirement_key", name="uq_conv_clarification_key"),
        Index("ix_conv_clarification_conv", "conversation_id"),
        Index("ix_conv_clarification_status", "status"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category_group: Mapped[str] = mapped_column(String(50), nullable=False)
    requirement_key: Mapped[str] = mapped_column(String(100), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ClarificationStatus] = mapped_column(
        Enum(ClarificationStatus, name="clarification_status", native_enum=False),
        default=ClarificationStatus.PENDING,
        nullable=False,
        index=True,
    )

    conversation: Mapped["ClientConversation"] = relationship(back_populates="clarifications")


class ClientPRD(UUIDPKMixin, TimestampMixin, Base):
    """
    Client Product Requirement Document (PRD) generated from verified requirements under Gate 4.

    Guarantees:
    - Anchored to a ClientConversation, Lead, and authenticated owner.
    - Versions are ordered and deterministic (unique per conversation_id, version).
    - Lifecycle states: DRAFT → PENDING_APPROVAL → APPROVED / REJECTED / SUPERSEDED.
    - Approved PRDs are immutable: once APPROVED, cannot be modified or re-approved.
    - Full requirement traceability preserved via references and JSON snapshot.
    """
    __tablename__ = "client_prds"
    __table_args__ = (
        UniqueConstraint("conversation_id", "version", name="uq_prd_conv_version"),
        Index("ix_client_prds_conv_id", "conversation_id"),
        Index("ix_client_prds_owner_email", "owner_email"),
        Index("ix_client_prds_status", "status"),
        Index("ix_client_prds_lead_id", "lead_id"),
    )

    owner_email: Mapped[str] = mapped_column(String(255), nullable=False)
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
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[PRDStatus] = mapped_column(
        Enum(PRDStatus, name="prd_status", native_enum=False),
        default=PRDStatus.PENDING_APPROVAL,
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    business_overview: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    goals: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    target_audience: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    sitemap: Mapped[List[Any]] = mapped_column(JSON, nullable=False)
    content_requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    functionality_requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    design_requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    branding_requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    contact_requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    technical_requirements: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    timeline: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    budget: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    assumptions: Mapped[List[str]] = mapped_column(JSON, nullable=False)
    open_questions: Mapped[List[Any]] = mapped_column(JSON, nullable=False)
    requirement_traceability: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    conversation: Mapped["ClientConversation"] = relationship(back_populates="prds")
    lead: Mapped["Lead"] = relationship(lazy="select")
    requirement_references: Mapped[List["ClientPRDRequirementReference"]] = relationship(
        back_populates="prd",
        cascade="all, delete-orphan",
        order_by="ClientPRDRequirementReference.section_key",
        lazy="select",
    )


class ClientPRDRequirementReference(UUIDPKMixin, Base):
    """
    Explicit entity linking a PRD section to an underlying ClientRequirement and message evidence.
    """
    __tablename__ = "client_prd_requirement_references"
    __table_args__ = (
        Index("ix_prd_req_ref_prd_id", "prd_id"),
        Index("ix_prd_req_ref_req_id", "requirement_id"),
    )

    prd_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_prds.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_requirements.id", ondelete="CASCADE"),
        nullable=False,
    )
    requirement_version: Mapped[int] = mapped_column(Integer, nullable=False)
    section_key: Mapped[str] = mapped_column(String(100), nullable=False)
    source_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_conversation_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    evidence_excerpt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    prd: Mapped["ClientPRD"] = relationship(back_populates="requirement_references")
    requirement: Mapped["ClientRequirement"] = relationship(lazy="select")

