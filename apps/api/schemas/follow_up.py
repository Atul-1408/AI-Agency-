"""
Pydantic schemas for Phase 4 Stage 4.4 — Follow-up Sequence and Scheduler Foundation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from models.follow_up import (
    FollowUpSequenceStatus,
    FollowUpStepStatus,
    FollowUpStopReason,
)


class CadenceStepConfig(BaseModel):
    """Configuration for a single step in a follow-up cadence."""
    model_config = ConfigDict(from_attributes=True)

    step_number: int = Field(..., ge=1, description="Step number in the sequence (1-indexed)")
    delay_hours: int = Field(..., ge=1, description="Delay in hours relative to initial outreach send")


class FollowUpStepResponse(BaseModel):
    """API representation of a scheduled follow-up step."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence_id: uuid.UUID
    step_number: int
    delay_hours: int
    status: FollowUpStepStatus
    scheduled_at: datetime
    executed_at: Optional[datetime] = None
    draft_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime


class FollowUpSequenceResponse(BaseModel):
    """API representation of a follow-up sequence with child steps."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    outreach_draft_id: Optional[uuid.UUID] = None
    original_message_id: Optional[uuid.UUID] = None
    status: FollowUpSequenceStatus
    current_step: int
    max_steps: int
    next_action_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    stop_reason: Optional[FollowUpStopReason] = None
    created_at: datetime
    updated_at: datetime
    steps: List[FollowUpStepResponse] = Field(default_factory=list)


class FollowUpSequenceCreateRequest(BaseModel):
    """Request payload to instantiate a follow-up sequence for a sent outreach message."""
    original_message_id: uuid.UUID = Field(
        ..., description="ID of the sent OutreachMessage to attach follow-up sequence to"
    )
    cadence: Optional[List[CadenceStepConfig]] = Field(
        default=None,
        description="Optional custom cadence step overrides. If omitted, default cadence is used.",
    )


class FollowUpSequenceStopRequest(BaseModel):
    """Request payload for manually stopping a sequence."""
    reason: Optional[FollowUpStopReason] = Field(
        default=FollowUpStopReason.OWNER_STOPPED,
        description="Reason for termination",
    )
    notes: Optional[str] = Field(default=None, max_length=500)


class ReplyDetectedRequest(BaseModel):
    """Payload to simulate or record a verified reply detection event."""
    detected_at: Optional[datetime] = Field(
        default=None, description="Timestamp reply was detected (UTC)"
    )
    gmail_message_id: Optional[str] = Field(
        default=None, description="External Gmail message ID of the detected reply"
    )
    snippet: Optional[str] = Field(
        default=None, max_length=500, description="Safe snippet of the reply without secrets"
    )


class FollowUpEligibilityCheckResponse(BaseModel):
    """Result of deterministic follow-up sequence/step eligibility evaluation."""
    eligible: bool = Field(..., description="Whether follow-up action is permitted to proceed")
    reason: Optional[str] = Field(default=None, description="Reason if ineligible")
    checks_passed: Dict[str, bool] = Field(default_factory=dict)


class DetectRepliesRequest(BaseModel):
    """Optional parameters for manual reply detection."""
    sequence_id: Optional[uuid.UUID] = Field(
        default=None, description="Optional specific follow-up sequence ID to check"
    )
    limit: int = Field(
        default=50, ge=1, le=100, description="Max sequences to inspect"
    )


class DetectRepliesResponse(BaseModel):
    """Detection run summary."""
    checked: int = Field(..., description="Number of sequences checked")
    replies_detected: int = Field(..., description="Number of verified prospect replies detected")
    sequences_stopped: int = Field(..., description="Number of sequences stopped due to replies")
    duplicates_ignored: int = Field(..., description="Number of duplicate messages ignored")


class InboundMessageResponse(BaseModel):
    """Safe representation of an inbound prospect message."""
    id: uuid.UUID
    gmail_message_id: str
    gmail_thread_id: str
    sender_email: str
    recipient_email: str
    subject: Optional[str] = None
    snippet: Optional[str] = None
    received_at: datetime
    detected_at: datetime
    matched_outreach_message_id: Optional[uuid.UUID] = None
    matched_lead_id: Optional[uuid.UUID] = None
    matched_sequence_id: Optional[uuid.UUID] = None
    processing_status: str

    model_config = ConfigDict(from_attributes=True)
