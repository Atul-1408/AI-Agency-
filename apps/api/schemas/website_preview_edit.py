"""
Phase 6 Stage 6.5 — Website Preview and Iterative Editing Schemas.

Defines Pydantic models for:
- WebsitePreview request and response payloads
- WebsiteEditSession request and response payloads
- WebsiteEditVersion request and response payloads
- Rollback and status payloads
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field


# ── Preview Schemas ───────────────────────────────────────────────────────────

class WebsitePreviewCreateRequest(BaseModel):
    """Request payload to instantiate a live preview for a project."""
    model_config = ConfigDict(extra="ignore")

    code_generation_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional explicit code generation ID. If omitted, uses latest completed generation.",
    )


class WebsitePreviewResponse(BaseModel):
    """Summary item for a live website preview."""
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    project_id: uuid.UUID
    build_session_id: uuid.UUID
    code_generation_id: uuid.UUID
    version: int = Field(..., description="Active version of website being previewed")
    status: str
    preview_token: str
    preview_url: str = Field(..., description="Controlled safe preview URL")
    port: Optional[int] = None
    workspace_reference: str
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    last_error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WebsitePreviewStatusResponse(BaseModel):
    """Real-time status response for an isolated preview instance."""
    model_config = ConfigDict(extra="ignore")

    preview_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    version: int
    is_running: bool
    uptime_seconds: Optional[int] = None
    preview_url: str
    last_error: Optional[str] = None


class WebsitePreviewListResponse(BaseModel):
    """List response for project previews."""
    model_config = ConfigDict(extra="ignore")

    previews: List[WebsitePreviewResponse] = Field(default_factory=list)
    total_count: int = 0


# ── Edit Schemas ──────────────────────────────────────────────────────────────

class WebsiteEditCreateRequest(BaseModel):
    """Request payload to initiate an AI-assisted iterative edit on the website."""
    model_config = ConfigDict(extra="ignore")

    owner_request: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="Owner's natural language modification request (e.g., 'Make the hero section darker')",
    )
    base_version: int = Field(
        ...,
        ge=1,
        description="Base version against which the edit is applied (for optimistic concurrency check)",
    )
    preview_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional active preview to update automatically upon successful edit",
    )


class WebsiteEditCancelRequest(BaseModel):
    """Request payload to cancel an active edit session."""
    model_config = ConfigDict(extra="ignore")

    reason: Optional[str] = Field(default=None, description="Optional cancellation reason")


class WebsiteEditResponse(BaseModel):
    """Summary item for an iterative edit session."""
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    project_id: uuid.UUID
    preview_id: Optional[uuid.UUID] = None
    base_code_generation_id: uuid.UUID
    base_version: int
    status: str
    owner_request: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WebsiteEditDetailResponse(BaseModel):
    """Detailed response for an edit session, including diff and affected files."""
    model_config = ConfigDict(extra="ignore")

    edit: WebsiteEditResponse
    changed_files: List[str] = Field(default_factory=list)
    diff_summary: Optional[str] = None
    version_created: Optional[int] = None
    new_version_id: Optional[uuid.UUID] = None


class WebsiteEditListResponse(BaseModel):
    """List response for project edit sessions."""
    model_config = ConfigDict(extra="ignore")

    edits: List[WebsiteEditResponse] = Field(default_factory=list)
    total_count: int = 0


# ── Version Schemas ───────────────────────────────────────────────────────────

class WebsiteEditVersionResponse(BaseModel):
    """Immutable version record representing a generated or edited website release."""
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    project_id: uuid.UUID
    edit_session_id: Optional[uuid.UUID] = None
    source_generation_id: uuid.UUID
    parent_version: Optional[int] = None
    version: int
    changed_files: List[str] = Field(default_factory=list)
    diff_summary: Optional[str] = None
    source_checksum: str
    artifact_id: Optional[uuid.UUID] = None
    is_active: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class WebsiteVersionListResponse(BaseModel):
    """List response for all immutable versions of a project."""
    model_config = ConfigDict(extra="ignore")

    versions: List[WebsiteEditVersionResponse] = Field(default_factory=list)
    current_version: int
    total_count: int = 0


class WebsiteVersionRollbackResponse(BaseModel):
    """Response payload after executing a rollback to a previous version."""
    model_config = ConfigDict(extra="ignore")

    message: str
    rolled_back_to_version: int
    new_version: int
    version_record: WebsiteEditVersionResponse
