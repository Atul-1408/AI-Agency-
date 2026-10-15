"""
Phase 9 Pydantic Schemas for Agent Workflow Orchestration.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from models.agent_workflow import WorkflowExecutionMode, WorkflowStage, WorkflowStatus


class WorkflowCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=255, description="Human-readable title for the workflow run")
    description: Optional[str] = Field(None, max_length=2000)
    mode: WorkflowExecutionMode = Field(default=WorkflowExecutionMode.SUPERVISED, description="manual, supervised, or dry_run")
    is_dry_run: bool = Field(default=False, description="When true, simulates execution without real external mutations")
    idempotency_key: Optional[str] = Field(None, max_length=255, description="Client token to prevent duplicate workflow creation")
    initial_data: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Initial parameters (e.g. business_type, city, domain)")


class WorkflowAdvanceRequest(BaseModel):
    action: str = Field(default="advance", description="'advance' to execute next step, 'retry' to re-attempt failed step")
    input_overrides: Optional[Dict[str, Any]] = Field(None, description="Optional overrides for step inputs")


class WorkflowApprovalActionRequest(BaseModel):
    decision: str = Field(..., pattern="^(approved|rejected)$", description="'approved' to continue, 'rejected' to abort")
    notes: Optional[str] = Field(None, max_length=1000, description="Owner review notes")


class WorkflowStepRecordResponse(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    stage: str
    status: str
    duration_ms: int
    input_snapshot: Optional[Dict[str, Any]] = None
    output_snapshot: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    is_dry_run: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowResponse(BaseModel):
    id: uuid.UUID
    owner_id: str
    title: str
    description: Optional[str] = None
    mode: WorkflowExecutionMode
    status: WorkflowStatus
    current_stage: WorkflowStage
    completed_stages: List[Dict[str, Any]] = Field(default_factory=list)
    pending_stages: List[str] = Field(default_factory=list)
    stage_data: Dict[str, Any] = Field(default_factory=dict)
    current_approval_id: Optional[uuid.UUID] = None
    error_state: Optional[Dict[str, Any]] = None
    is_dry_run: bool
    idempotency_key: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    step_records: Optional[List[WorkflowStepRecordResponse]] = None

    model_config = {"from_attributes": True}


class WorkflowListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[WorkflowResponse]


class ProviderConnectivityResponse(BaseModel):
    database: Dict[str, Any]
    redis_queue: Dict[str, Any]
    ai_provider: Dict[str, Any]
    gmail: Dict[str, Any]
    github: Dict[str, Any]
    vercel: Dict[str, Any]
    environment: str
    summary: str
