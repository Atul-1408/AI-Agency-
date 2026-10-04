"""
Pydantic schemas for Phase 6 Stage 6.1 — AI Website Builder Foundation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from models.website_builder import (
    WebsiteBuildArtifactType,
    WebsiteBuildSessionStatus,
)


class WebsiteBuildArtifactResponse(BaseModel):
    """Representation of a build artifact record."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    build_session_id: uuid.UUID
    project_id: uuid.UUID
    artifact_type: WebsiteBuildArtifactType
    artifact_name: str
    artifact_version: int
    content_reference: Optional[str] = None
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata", "artifact_metadata"),
    )
    created_at: datetime
    updated_at: datetime


class WebsiteBuildSessionResponse(BaseModel):
    """API representation of a Website Build Session."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    owner_id: str
    status: WebsiteBuildSessionStatus
    build_version: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata", "build_metadata"),
    )
    created_at: datetime
    updated_at: datetime


class WebsiteBuildSessionDetailResponse(WebsiteBuildSessionResponse):
    """Enriched build session details including artifacts and PRD handoff metadata."""
    artifacts: List[WebsiteBuildArtifactResponse] = Field(default_factory=list)
    project_name: Optional[str] = None
    project_slug: Optional[str] = None
    project_status: Optional[str] = None
    approved_prd_id: Optional[uuid.UUID] = None
    approved_prd_version: Optional[int] = None
    prd_summary: Optional[Dict[str, Any]] = None


class WebsiteBuildSessionListResponse(BaseModel):
    """Paginated or metric-enriched list of build sessions for a project."""
    items: List[WebsiteBuildSessionResponse]
    total: int
    active_count: int
    completed_count: int
    failed_count: int


# ── Action Request Schemas ────────────────────────────────────────────────────

class BuildSessionTransitionRequest(BaseModel):
    """Optional payload for state machine transitions."""
    notes: Optional[str] = Field(default=None, max_length=500)


class BuildSessionCancelRequest(BaseModel):
    """Payload when cancelling a build session."""
    reason: Optional[str] = Field(default=None, max_length=500)


class BuildSessionPauseRequest(BaseModel):
    """Payload when pausing a build session."""
    reason: Optional[str] = Field(default=None, max_length=500)
