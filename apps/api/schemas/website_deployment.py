"""
Phase 8 — Website Deployment Pydantic Schemas.

Models for request validation and sanitized API responses.
Security Guarantee: Access tokens and credentials are NEVER exposed in any response schema.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field

from models.website_deployment import (
    DeploymentEnvironment,
    DeploymentProvider,
    WebsiteDeploymentStatus,
)


class WebsiteDeploymentCreateRequest(BaseModel):
    """Payload to request a deployment (initiates Gate 5 approval if production)."""
    environment: DeploymentEnvironment = Field(
        default=DeploymentEnvironment.PRODUCTION,
        description="Deployment target environment (preview or production)",
    )
    target_version: Optional[int] = Field(
        default=None,
        description="Specific source code version to deploy (defaults to active verified version)",
    )
    code_generation_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional explicit code generation ID",
    )
    qa_run_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional explicit QA run ID to bind to",
    )
    custom_domain: Optional[str] = Field(
        default=None,
        description="Optional custom domain to configure (e.g. clientsite.com)",
    )
    github_repo_name: Optional[str] = Field(
        default=None,
        description="Optional explicit repository name",
    )
    github_branch: Optional[str] = Field(
        default="main",
        description="Git branch to commit and publish to",
    )
    force_mock: bool = Field(
        default=False,
        description="Force use of mock provider (useful for deterministic tests)",
    )


class WebsiteDeploymentApproveRequest(BaseModel):
    """Payload for owner Gate 5 approval."""
    notes: Optional[str] = Field(
        default=None,
        description="Optional owner review note",
    )


class WebsiteDeploymentExecuteRequest(BaseModel):
    """Payload to execute an approved deployment."""
    force_mock: bool = Field(
        default=False,
        description="Force use of mock provider during execution",
    )


class WebsiteDeploymentCancelRequest(BaseModel):
    """Payload to safely cancel an unexecuted deployment."""
    reason: Optional[str] = Field(
        default=None,
        description="Reason for cancellation",
    )


class WebsiteDeploymentDomainRequest(BaseModel):
    """Payload to bind a custom domain."""
    domain: str = Field(
        ...,
        min_length=3,
        max_length=253,
        description="Domain name to bind (e.g., example.com)",
    )


class DNSRecordSchema(BaseModel):
    """Required DNS record specification for custom domain setup."""
    type: str  # A, CNAME, TXT
    name: str  # @, www, etc.
    value: str # 76.76.21.21, cname.vercel-dns.com
    description: Optional[str] = None


class WebsiteDeploymentResponse(BaseModel):
    """Public deployment response payload — credentials are never exposed."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: str
    project_id: uuid.UUID
    build_session_id: uuid.UUID
    code_generation_id: uuid.UUID
    qa_run_id: uuid.UUID
    source_version: int
    source_checksum: str
    environment: DeploymentEnvironment
    status: WebsiteDeploymentStatus
    provider: DeploymentProvider

    deployment_url: Optional[str] = None
    production_url: Optional[str] = None
    custom_domain: Optional[str] = None
    dns_records: List[Dict[str, Any]] = Field(default_factory=list)
    ssl_status: str

    github_repo_url: Optional[str] = None
    github_repo_name: Optional[str] = None
    github_branch: Optional[str] = "main"
    github_commit_sha: Optional[str] = None

    provider_deployment_id: Optional[str] = None
    build_logs: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    approval_request_id: Optional[uuid.UUID] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class WebsiteDeploymentEligibilityResponse(BaseModel):
    """Verification results determining whether a project can be safely deployed."""
    eligible: bool
    reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    project_id: uuid.UUID
    target_version: Optional[int] = None
    code_generation_id: Optional[uuid.UUID] = None
    qa_run_id: Optional[uuid.UUID] = None
    qa_status: Optional[str] = None
    qa_score: Optional[int] = None
    blocker_findings: int = 0
    high_findings: int = 0
    source_checksum: Optional[str] = None
    has_pending_approval: bool = False
    approval_status: Optional[str] = None
