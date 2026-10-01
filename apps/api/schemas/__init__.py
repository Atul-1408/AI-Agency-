"""
Phase 1 Pydantic schemas for request/response validation.
Only schemas for Phase 1 endpoints are defined here.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from models import AgentRunStatus, ApprovalStatus, EmailVerificationStatus, LeadStatus


# ── Shared ────────────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[Any]


# ── Auth ──────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(..., description="Owner email address")
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int    # seconds until expiry


# ── Agent Runs ────────────────────────────────────────────────────────────────

class TriggerAgentRequest(BaseModel):
    agent_name: str = Field(
        ...,
        description="Registered agent name. Phase 1: only 'orchestrator' is active.",
    )
    input_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional key-value input passed to the agent.",
    )


class AgentRunResponse(BaseModel):
    id: uuid.UUID
    agent_name: str
    job_id: Optional[str]
    status: AgentRunStatus
    input_data: Optional[Dict[str, Any]]
    output_data: Optional[Dict[str, Any]]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    tokens_used: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Approval Requests ─────────────────────────────────────────────────────────

class ApprovalResponse(BaseModel):
    id: uuid.UUID
    action_type: str
    payload: Dict[str, Any]
    status: ApprovalStatus
    owner_note: Optional[str]
    reviewed_at: Optional[datetime]
    agent_run_id: Optional[uuid.UUID]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ApprovalDecision(BaseModel):
    decision: ApprovalStatus = Field(
        ...,
        description="Must be 'approved' or 'rejected'. 'pending' is not a valid decision.",
    )
    owner_note: Optional[str] = Field(
        default=None,
        description="Optional note from the owner explaining the decision.",
    )

    def model_post_init(self, __context: Any) -> None:
        if self.decision == ApprovalStatus.PENDING:
            raise ValueError("Cannot set decision to 'pending'.")


# ── Health ────────────────────────────────────────────────────────────────────

class ServiceStatus(BaseModel):
    status: str     # "ok" | "unavailable" | "error"
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str     # "ok" | "degraded"
    version: str
    environment: str
    services: Dict[str, ServiceStatus]


# ── Phase 2: Leads ────────────────────────────────────────────────────────────

class LeadResearchResponse(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    has_website: bool
    is_responsive: Optional[bool]
    has_ssl: Optional[bool]
    status_code: Optional[int]
    load_time_ms: Optional[int]
    copyright_year: Optional[int]
    tech_stack: Optional[Dict[str, Any]]
    audit_findings: Optional[Dict[str, Any]]
    research_notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadResponse(BaseModel):
    id: uuid.UUID
    company_name: str
    domain: str
    website_url: Optional[str]
    google_place_id: Optional[str] = None
    phone: Optional[str]
    email: Optional[str]
    email_verification_status: EmailVerificationStatus
    address: Optional[str]
    city: Optional[str] = None
    industry: Optional[str]
    qualification_score: int
    status: LeadStatus
    rejection_reason: Optional[str]
    source_type: str
    source_query: Optional[str]
    source_url: Optional[str]
    research: Optional[LeadResearchResponse] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiscoverLeadsRequest(BaseModel):
    query: str = Field(..., min_length=2, description="Target business niche or query, e.g. 'plumbers'")
    location: Optional[str] = Field(default=None, description="Target city or area, e.g. 'Austin, TX'")
    limit: int = Field(default=10, ge=1, le=20, description="Max prospects to discover (batch limit: 20)")
    provider: str = Field(default="google_places", description="Discovery provider name ('google_places' or 'manual_entry')")


class ManualLeadCreateRequest(BaseModel):
    company_name: str = Field(..., min_length=1, description="Business name")
    website_url: Optional[str] = Field(default=None, description="Official website URL")
    domain: Optional[str] = Field(default=None, description="Domain name (auto-derived if omitted)")
    phone: Optional[str] = Field(default=None, description="Public phone number")
    address: Optional[str] = Field(default=None, description="Business address")
    city: Optional[str] = Field(default=None, description="City or locality")
    industry: Optional[str] = Field(default=None, description="Industry/category")
    notes: Optional[str] = Field(default=None, description="Owner notes")


class LeadRejectRequest(BaseModel):
    reason: Optional[str] = Field(default=None, description="Reason for rejecting the lead")


# ── Phase 3 Schemas ───────────────────────────────────────────────────────────

from schemas.outreach import (
    DeliveryEventResponse,
    GmailAccountCreate,
    GmailAccountResponse,
    OutreachDraftCreate,
    OutreachDraftResponse,
    OutreachMessageResponse,
    SendAttemptResponse,
    SuppressionRecordCreate,
    SuppressionRecordResponse,
)

__all__ = [
    # Shared
    "PaginatedResponse",
    # Auth
    "LoginRequest",
    "TokenResponse",
    # Phase 1
    "TriggerAgentRequest",
    "AgentRunResponse",
    "ReviewApprovalRequest",
    "ApprovalRequestResponse",
    # Phase 2
    "LeadResponse",
    "LeadResearchResponse",
    "DiscoverLeadsRequest",
    "ManualLeadCreateRequest",
    "LeadRejectRequest",
    # Phase 3
    "OutreachDraftCreate",
    "OutreachDraftResponse",
    "GmailAccountCreate",
    "GmailAccountResponse",
    "OutreachMessageResponse",
    "SendAttemptResponse",
    "SuppressionRecordCreate",
    "SuppressionRecordResponse",
    "DeliveryEventResponse",
]

