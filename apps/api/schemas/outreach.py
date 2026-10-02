"""
Phase 3 Pydantic schemas for Outreach Agent models.

Stage 3.1 scope:
- Data validation schemas for outreach models
- Security requirement: encrypted_refresh_token is strictly EXCLUDED from all response schemas.
- SuppressionRecord validation ensures at least email or domain is populated.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from models.outreach import (
    DeliveryEventType,
    GmailConnectionStatus,
    OutreachDraftStatus,
    OutreachMessageStatus,
    SendAttemptResult,
    SuppressionReason,
)


# ── Outreach Draft Schemas ────────────────────────────────────────────────────

class OutreachDraftCreate(BaseModel):
    lead_id: uuid.UUID = Field(..., description="ID of the qualified, approved lead")
    recipient_email: str = Field(..., description="Target business contact email")
    subject: str = Field(..., min_length=1, max_length=500, description="Email subject line")
    body_text: str = Field(..., min_length=1, description="Plaintext email content")
    body_html: Optional[str] = Field(default=None, description="HTML formatted email content")


class OutreachDraftUpdateRequest(BaseModel):
    subject: Optional[str] = Field(default=None, min_length=1, max_length=500, description="Updated subject line")
    body_text: Optional[str] = Field(default=None, min_length=1, description="Updated plaintext body")
    body_html: Optional[str] = Field(default=None, description="Updated HTML body")

    @field_validator("subject", "body_text")
    @classmethod
    def validate_non_empty_if_present(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Field cannot be empty or whitespace only if provided")
        return v.strip() if v is not None else None


class OutreachDraftRejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=1000, description="Mandatory reason for rejection")

    @field_validator("reason")
    @classmethod
    def validate_reason_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Rejection reason cannot be empty or whitespace only")
        return v.strip()


class OutreachDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    company_name: Optional[str] = None
    lead_domain: Optional[str] = None
    recipient_email: str
    subject: str
    body_text: str
    body_html: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    status: OutreachDraftStatus
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejected_by: Optional[str] = None
    rejection_reason: Optional[str] = None
    follow_up_sequence_id: Optional[uuid.UUID] = None
    follow_up_step_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


# ── Gmail Account Schemas ─────────────────────────────────────────────────────

class GmailAccountCreate(BaseModel):
    """
    Used internally to register or update an encrypted token.
    OAuth handshake is handled in Stage 3.2.
    """
    google_email: str = Field(..., description="Owner's Google Workspace / Gmail address")
    encrypted_refresh_token: str = Field(..., min_length=1, description="AES-GCM encrypted token")


class GmailAccountResponse(BaseModel):
    """
    Public/API representation of connected Gmail account.
    CRITICAL SECURITY RULE: NEVER expose encrypted_refresh_token.
    """
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: str
    google_email: str
    token_created_at: datetime
    last_token_refresh_at: Optional[datetime] = None
    connection_status: GmailConnectionStatus
    last_health_check: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ── Outreach Message Schemas ──────────────────────────────────────────────────

class OutreachMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    draft_id: Optional[uuid.UUID] = None
    lead_id: uuid.UUID
    recipient_email: str
    subject: str
    gmail_message_id: Optional[str] = None
    gmail_thread_id: Optional[str] = None
    sent_at: datetime
    status: OutreachMessageStatus
    created_at: datetime
    updated_at: datetime


# ── Send Attempt Schemas ──────────────────────────────────────────────────────

class SendAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    draft_id: Optional[uuid.UUID] = None
    lead_id: uuid.UUID
    recipient_email: str
    attempted_at: datetime
    result: SendAttemptResult
    failure_reason: Optional[str] = None
    gmail_message_id: Optional[str] = None
    gmail_thread_id: Optional[str] = None
    created_at: datetime


# ── Suppression Record Schemas ────────────────────────────────────────────────

class SuppressionRecordCreate(BaseModel):
    email: Optional[str] = Field(default=None, description="Individual email to suppress")
    domain: Optional[str] = Field(default=None, description="Entire domain to suppress")
    reason: SuppressionReason = Field(..., description="Root cause justification")
    notes: Optional[str] = Field(default=None, description="Optional context or ticket reference")
    source: str = Field(default="manual", description="Origin of suppression rule")

    @model_validator(mode="after")
    def validate_target_present(self) -> SuppressionRecordCreate:
        has_email = bool(self.email and self.email.strip())
        has_domain = bool(self.domain and self.domain.strip())
        if not has_email and not has_domain:
            raise ValueError("At least one of 'email' or 'domain' must be provided and non-empty")
        return self


class SuppressionRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: Optional[str] = None
    domain: Optional[str] = None
    reason: SuppressionReason
    notes: Optional[str] = None
    source: str
    created_at: datetime
    updated_at: datetime


# ── Delivery Event Schemas ────────────────────────────────────────────────────

class DeliveryEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    outreach_message_id: uuid.UUID
    event_type: DeliveryEventType
    event_timestamp: datetime
    metadata_json: Optional[Dict[str, Any]] = Field(default=None, alias="metadata")
    created_at: datetime


# ── Gmail Dispatch Schemas (Phase 4 Stage 4.3) ────────────────────────────────

class GmailDispatchResponse(BaseModel):
    """Result of single manual email dispatch via Gmail API."""
    model_config = ConfigDict(from_attributes=True)

    success: bool = Field(..., description="Whether the email was accepted and sent by Gmail API")
    draft_id: uuid.UUID = Field(..., description="ID of the sent OutreachDraft")
    lead_id: uuid.UUID = Field(..., description="ID of the associated Lead")
    recipient_email: str = Field(..., description="Recipient email address")
    subject: str = Field(..., description="Subject line sent")
    gmail_message_id: str = Field(..., description="Gmail message ID assigned by Google")
    gmail_thread_id: str = Field(..., description="Gmail thread ID assigned by Google")
    sent_at: datetime = Field(..., description="Timestamp of dispatch")
    status: str = Field(default="sent", description="Lifecycle state of dispatch")

