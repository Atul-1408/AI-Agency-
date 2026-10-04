"""
Pydantic schemas for Phase 5 Stage 5.1 — Client Conversation Foundation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from models.client_intelligence import (
    ClarificationStatus,
    ClientConversationStatus,
    MessageDirection,
    PRDStatus,
    RequirementConfidence,
    RequirementStatus,
)


# ── Message Schemas ───────────────────────────────────────────────────────────

class ConversationMessageResponse(BaseModel):
    """API representation of a single normalized conversation message."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    gmail_message_id: str
    gmail_thread_id: str
    sender_email: str
    recipient_email: str
    subject: Optional[str] = None
    direction: MessageDirection
    # body_text is UNTRUSTED EXTERNAL DATA — clients must render as escaped plain text
    body_text: Optional[str] = None
    received_at: datetime
    position: int
    created_at: datetime
    updated_at: datetime


# ── Conversation Schemas ──────────────────────────────────────────────────────

class ConversationCreateRequest(BaseModel):
    """Request payload to create a new client conversation."""
    lead_id: uuid.UUID = Field(
        ..., description="ID of the Lead that has replied (must have verified InboundMessage)"
    )
    inbound_message_id: Optional[uuid.UUID] = Field(
        default=None,
        description=(
            "Optional: specific InboundMessage to anchor the conversation to. "
            "If omitted, the most recent InboundMessage for the lead is used."
        ),
    )


class ConversationResponse(BaseModel):
    """API representation of a ClientConversation (without messages)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    inbound_message_id: Optional[uuid.UUID] = None
    gmail_thread_id: str
    status: ClientConversationStatus
    fetched_at: Optional[datetime] = None
    message_count: Optional[int] = None
    last_message_at: Optional[datetime] = None
    # Owner annotation fields (populated in Stage 5.2)
    intent: Optional[str] = None
    budget_signal: Optional[str] = None
    timeline_signal: Optional[str] = None
    owner_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ConversationDetailResponse(BaseModel):
    """API representation of a ClientConversation with normalized messages."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    inbound_message_id: Optional[uuid.UUID] = None
    gmail_thread_id: str
    status: ClientConversationStatus
    fetched_at: Optional[datetime] = None
    message_count: Optional[int] = None
    last_message_at: Optional[datetime] = None
    intent: Optional[str] = None
    budget_signal: Optional[str] = None
    timeline_signal: Optional[str] = None
    owner_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: List[ConversationMessageResponse] = Field(default_factory=list)


# ── Requirement Schemas ───────────────────────────────────────────────────────

class RequirementEvidenceResponse(BaseModel):
    """Traceable evidence linking a requirement to a specific email message."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requirement_id: uuid.UUID
    conversation_message_id: uuid.UUID
    source_message_direction: MessageDirection
    excerpt: str
    extraction_method: str
    confidence: RequirementConfidence
    created_at: datetime


class RequirementVersionResponse(BaseModel):
    """Historical version entry showing value transitions over time."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    requirement_id: uuid.UUID
    version_number: int
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    change_reason: Optional[str] = None
    source_message_id: Optional[uuid.UUID] = None
    created_at: datetime


class RequirementResponse(BaseModel):
    """API representation of an extracted client requirement."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    key: str
    category_group: str
    value: Optional[Any] = None
    status: RequirementStatus
    confidence: RequirementConfidence
    current_version: int
    notes: Optional[str] = None
    evidence_count: int = 0
    version_count: int = 0
    created_at: datetime
    updated_at: datetime


class RequirementDetailResponse(BaseModel):
    """API representation of a requirement with full evidence trail and history."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    key: str
    category_group: str
    value: Optional[Any] = None
    status: RequirementStatus
    confidence: RequirementConfidence
    current_version: int
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    evidence: List[RequirementEvidenceResponse] = Field(default_factory=list)
    versions: List[RequirementVersionResponse] = Field(default_factory=list)


# ── Clarification Schemas ────────────────────────────────────────────────────

class ClarificationResponse(BaseModel):
    """Structured question for missing or ambiguous client requirements."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    category_group: str
    requirement_key: str
    question: str
    rationale: str
    status: ClarificationStatus
    created_at: datetime
    updated_at: datetime


# ── Completeness Schemas ─────────────────────────────────────────────────────

class CategoryCompletenessResponse(BaseModel):
    """Completeness score and status for a single requirement category."""
    category: str
    status: str  # "complete", "partial", "empty"
    total_fields: int
    present_fields: List[str]
    missing_fields: List[str]
    completeness_percentage: float


class ConversationCompletenessResponse(BaseModel):
    """Full deterministic completeness assessment across all categories."""
    conversation_id: uuid.UUID
    overall_completeness_percentage: float
    overall_status: str  # "complete", "partial", "empty"
    categories: List[CategoryCompletenessResponse]
    total_fields: int
    total_present: int
    total_missing: int


# ── Extraction Execution Response ─────────────────────────────────────────────

class ExtractionResponse(BaseModel):
    """Response returned upon running requirement extraction on a conversation."""
    conversation_id: uuid.UUID
    status: ClientConversationStatus
    requirements_count: int
    clarifications_count: int
    overall_completeness_percentage: float
    requirements: List[RequirementResponse] = Field(default_factory=list)
    clarifications: List[ClarificationResponse] = Field(default_factory=list)


# ── PRD Schemas (Phase 5.3) ──────────────────────────────────────────────────

class PRDRequirementReferenceResponse(BaseModel):
    """Traceable reference linking a PRD section to an underlying ClientRequirement."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prd_id: uuid.UUID
    requirement_id: uuid.UUID
    requirement_version: int
    section_key: str
    source_message_id: Optional[uuid.UUID] = None
    evidence_excerpt: Optional[str] = None
    created_at: datetime


class PRDResponse(BaseModel):
    """API representation of a ClientPRD record."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_email: str
    lead_id: uuid.UUID
    conversation_id: uuid.UUID
    version: int
    status: PRDStatus
    title: str
    executive_summary: str
    business_overview: Dict[str, Any]
    goals: List[str]
    target_audience: Optional[Any] = None
    sitemap: List[Any]
    content_requirements: Dict[str, Any]
    functionality_requirements: Dict[str, Any]
    design_requirements: Dict[str, Any]
    branding_requirements: Dict[str, Any]
    contact_requirements: Dict[str, Any]
    technical_requirements: Dict[str, Any]
    timeline: Dict[str, Any]
    budget: Dict[str, Any]
    assumptions: List[str]
    open_questions: List[Any]
    requirement_traceability: Dict[str, Any]
    generated_at: datetime
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PRDDetailResponse(PRDResponse):
    """Detailed PRD representation with granular requirement references."""
    requirement_references: List[PRDRequirementReferenceResponse] = Field(default_factory=list)
    completeness: Optional[ConversationCompletenessResponse] = None


class PRDApproveRequest(BaseModel):
    """Request payload to approve a PRD under Gate 4."""
    notes: Optional[str] = Field(default=None, description="Optional approval notes by owner")


class PRDRejectRequest(BaseModel):
    """Request payload to reject a PRD under Gate 4."""
    rejection_reason: Optional[str] = Field(
        default=None, description="Optional reason explaining why the PRD was rejected"
    )


class PRDGenerateRequest(BaseModel):
    """Request payload to generate a PRD for a conversation."""
    conversation_id: uuid.UUID = Field(..., description="ID of the conversation to generate PRD for")

