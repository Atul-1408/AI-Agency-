"""
Phase 7 — Automated Website QA & Evaluator Schemas.
Pydantic v2 schemas for QA execution, quality findings, and automated repairs.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from models.website_qa import (
    QAFindingCategory,
    QAFindingSeverity,
    WebsiteQARunStatus,
)


class WebsiteQARunCreateRequest(BaseModel):
    """Request payload to initiate an automated QA evaluation."""
    model_config = ConfigDict(extra="forbid")

    code_generation_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional specific completed code generation ID to evaluate. Defaults to latest.",
    )
    target_version: Optional[int] = Field(
        default=None,
        description="Target website version to evaluate. Defaults to active version.",
    )


class WebsiteQAFindingResponse(BaseModel):
    """Structured QA finding or defect."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    qa_run_id: uuid.UUID
    project_id: uuid.UUID
    severity: QAFindingSeverity
    category: QAFindingCategory
    title: str
    description: str
    affected_route: str
    affected_file: Optional[str] = None
    evidence: Optional[str] = None
    reproduction_steps: Optional[str] = None
    suggested_repair: Optional[str] = None
    is_repaired: bool
    repaired_at: Optional[datetime] = None
    repaired_in_version: Optional[int] = None
    created_at: datetime


class WebsiteQARunResponse(BaseModel):
    """Summary of an automated QA execution run."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    build_session_id: uuid.UUID
    source_generation_id: uuid.UUID
    target_version: int
    owner_id: str
    status: WebsiteQARunStatus
    total_checks: int
    passed_checks: int
    failed_checks: int
    warning_checks: int
    skipped_checks: int
    score: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WebsiteQARunDetailResponse(BaseModel):
    """Detailed QA report with full findings and deployment readiness check."""
    model_config = ConfigDict(from_attributes=True)

    run: WebsiteQARunResponse
    findings: List[WebsiteQAFindingResponse]
    summary_by_severity: Dict[str, int]
    summary_by_category: Dict[str, int]
    can_deploy: bool


class WebsiteQARunListResponse(BaseModel):
    """List of QA runs for a project."""
    model_config = ConfigDict(from_attributes=True)

    items: List[WebsiteQARunResponse]
    total: int


class WebsiteQAFindingRepairRequest(BaseModel):
    """Request payload to automatically repair a QA finding."""
    model_config = ConfigDict(extra="forbid")

    preview_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional preview ID to sync updated preview with the repaired version.",
    )


class WebsiteQAFindingRepairResponse(BaseModel):
    """Result of an automated finding repair execution."""
    model_config = ConfigDict(from_attributes=True)

    finding_id: uuid.UUID
    is_repaired: bool
    new_version: int
    diff_summary: Optional[str] = None
    message: str
