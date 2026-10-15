"""
Phase 8 — Production Deployment & Hosting Models.

Entities defined:
- DeploymentEnvironment: preview vs. production.
- WebsiteDeploymentStatus: Lifecycle state machine for deployments.
- DeploymentProvider: vercel, github, mock.
- WebsiteDeployment: Orchestrated deployment record linking project, code generation,
  passing QA run, owner approval, GitHub commit/repo, and live Vercel URLs.
"""
from __future__ import annotations

from datetime import datetime
import enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base
from models import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from models.project import Project
    from models.website_builder import WebsiteBuildSession, WebsiteCodeGeneration
    from models.website_qa import WebsiteQARun
    from models import ApprovalRequest


# ── Enums ─────────────────────────────────────────────────────────────────────

class DeploymentEnvironment(str, enum.Enum):
    PREVIEW    = "preview"
    PRODUCTION = "production"


class WebsiteDeploymentStatus(str, enum.Enum):
    """
    Lifecycle states for Phase 8 deployments:
    READY_FOR_DEPLOYMENT -> AWAITING_APPROVAL -> APPROVED -> DEPLOYING -> DEPLOYED / FAILED (or CANCELLED)
    """
    READY_FOR_DEPLOYMENT = "ready_for_deployment"
    AWAITING_APPROVAL    = "awaiting_approval"
    APPROVED             = "approved"
    DEPLOYING            = "deploying"
    DEPLOYED             = "deployed"
    FAILED               = "failed"
    CANCELLED            = "cancelled"


class DeploymentProvider(str, enum.Enum):
    VERCEL = "vercel"
    GITHUB = "github"
    MOCK   = "mock"


# ── WebsiteDeployment Model ───────────────────────────────────────────────────

class WebsiteDeployment(UUIDPKMixin, TimestampMixin, Base):
    """
    Production or Preview Deployment record for a validated website project.
    Strictly anchored to:
    - Authenticated owner_id
    - Project ID and approved PRD version
    - Target code generation ID and immutable source version
    - Successful QA run ID with 0 blocker / high defects
    - Explicit Gate 5 owner approval
    """
    __tablename__ = "website_deployments"
    __table_args__ = (
        Index("ix_website_deployments_owner_id", "owner_id"),
        Index("ix_website_deployments_project_id", "project_id"),
        Index("ix_website_deployments_status", "status"),
        Index("ix_website_deployments_code_gen_id", "code_generation_id"),
        Index("ix_website_deployments_qa_run_id", "qa_run_id"),
    )

    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    build_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_build_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_code_generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    qa_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_qa_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)

    environment: Mapped[DeploymentEnvironment] = mapped_column(
        Enum(DeploymentEnvironment, name="deployment_environment", native_enum=False),
        default=DeploymentEnvironment.PRODUCTION,
        nullable=False,
    )
    status: Mapped[WebsiteDeploymentStatus] = mapped_column(
        Enum(WebsiteDeploymentStatus, name="website_deployment_status", native_enum=False),
        default=WebsiteDeploymentStatus.READY_FOR_DEPLOYMENT,
        nullable=False,
    )
    provider: Mapped[DeploymentProvider] = mapped_column(
        Enum(DeploymentProvider, name="deployment_provider", native_enum=False),
        default=DeploymentProvider.VERCEL,
        nullable=False,
    )

    # Deployment URLs
    deployment_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    production_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    custom_domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dns_records: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    ssl_status: Mapped[str] = mapped_column(String(50), default="unconfigured", nullable=False)

    # GitHub Provenance
    github_repo_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    github_repo_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    github_branch: Mapped[Optional[str]] = mapped_column(String(100), default="main", nullable=True)
    github_commit_sha: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Provider identifiers & execution telemetry
    provider_deployment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    build_logs: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Gate 5 Owner Approval Binding
    approval_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Execution Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_info: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    project: Mapped["Project"] = relationship(lazy="select")
    build_session: Mapped["WebsiteBuildSession"] = relationship(lazy="select")
    code_generation: Mapped["WebsiteCodeGeneration"] = relationship(lazy="select")
    qa_run: Mapped["WebsiteQARun"] = relationship(lazy="select")
    approval_request: Mapped[Optional["ApprovalRequest"]] = relationship(lazy="select")
