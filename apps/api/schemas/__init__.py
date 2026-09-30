"""
Phase 1 Pydantic schemas for request/response validation.
Only schemas for Phase 1 endpoints are defined here.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from models import AgentRunStatus, ApprovalStatus


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
