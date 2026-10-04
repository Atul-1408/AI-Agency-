"""
Pydantic schemas for Phase 5 Stage 5.4 — Project Creation & Lifecycle Foundation.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.project import ProjectStatus


# Dangerous characters/patterns for project names
HTML_SCRIPT_PATTERN = re.compile(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>|<[^>]+>", re.IGNORECASE | re.DOTALL)
DANGEROUS_CHARS_PATTERN = re.compile(r"[\x00-\x1f\x7f;<>\'\"\`\$\{\}\\]")


class ProjectCreateRequest(BaseModel):
    """
    Request to create a project from an approved PRD.
    Security: owner_id, lead_id, conversation_id, approved_by, approved_at, and project_status
    are STRICTLY server-controlled and cannot be specified by the client.
    """
    approved_prd_id: uuid.UUID = Field(
        ...,
        description="UUID of the Approved PRD under Gate 4",
    )
    custom_project_name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Optional human-specified project name. If omitted, derived from PRD / lead data.",
    )

    @field_validator("custom_project_name")
    @classmethod
    def sanitize_project_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            return None
        if len(cleaned) < 2:
            raise ValueError("Project name must be at least 2 characters long")
        if HTML_SCRIPT_PATTERN.search(cleaned):
            raise ValueError("Project name cannot contain HTML or script tags")
        if DANGEROUS_CHARS_PATTERN.search(cleaned):
            raise ValueError("Project name contains invalid characters")
        return cleaned


class ProjectUpdateRequest(BaseModel):
    """
    Request to update a project.
    Strictly mutable fields only: project_name, project_status (limited), phase_metadata.
    Immutable: owner_id, lead_id, conversation_id, approved_prd_id, prd_version,
    created_by, created_at, approved_at.
    """
    project_name: Optional[str] = Field(default=None, max_length=255)
    project_status: Optional[ProjectStatus] = Field(
        default=None,
        description="In Phase 5.4, only READY_FOR_BUILD or CANCELLED are allowed.",
    )
    phase_metadata: Optional[Dict[str, Any]] = None

    @field_validator("project_name")
    @classmethod
    def sanitize_project_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Project name cannot be empty")
        if len(cleaned) < 2:
            raise ValueError("Project name must be at least 2 characters long")
        if HTML_SCRIPT_PATTERN.search(cleaned):
            raise ValueError("Project name cannot contain HTML or script tags")
        if DANGEROUS_CHARS_PATTERN.search(cleaned):
            raise ValueError("Project name contains invalid characters")
        return cleaned

    @field_validator("project_status")
    @classmethod
    def validate_phase5_status(cls, v: Optional[ProjectStatus]) -> Optional[ProjectStatus]:
        if v is None:
            return None
        # Phase 5.4 restricts transitions to safe lifecycle states (e.g. CANCELLED or READY_FOR_BUILD)
        # Phase 6/7/8 statuses (IN_BUILD, QA, DEPLOYED, etc.) cannot be set by client in Phase 5.4
        allowed_statuses = {ProjectStatus.READY_FOR_BUILD, ProjectStatus.CANCELLED}
        if v not in allowed_statuses:
            raise ValueError(
                f"Status transition to '{v.value}' is not permitted in Phase 5.4. "
                f"Build and deployment lifecycle transitions belong to future phases."
            )
        return v


class ProjectResponse(BaseModel):
    """Standard project response representation."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: str
    lead_id: uuid.UUID
    conversation_id: uuid.UUID
    approved_prd_id: uuid.UUID
    prd_version: int
    project_name: str
    project_slug: str
    project_status: ProjectStatus
    project_source: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    phase_metadata: Dict[str, Any] = Field(default_factory=dict)


class ProjectDetailResponse(ProjectResponse):
    """Enriched project response with business, conversation, PRD, and handoff summaries."""
    business_name: Optional[str] = None
    business_domain: Optional[str] = None
    business_type: Optional[str] = None
    lead_info: Optional[Dict[str, Any]] = None
    conversation_summary: Optional[Dict[str, Any]] = None
    prd_summary: Optional[Dict[str, Any]] = None
    requirements_summary: Optional[Dict[str, Any]] = None
    handoff_readiness: Optional[Dict[str, Any]] = None


class ProjectListResponse(BaseModel):
    """Dashboard projects listing response."""
    items: List[ProjectResponse]
    total: int
    ready_for_build_count: int
    in_build_count: int
    completed_count: int
