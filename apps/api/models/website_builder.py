"""
Phase 6 Stage 6.1 — AI Website Builder Foundation Models.

Entities defined:
- WebsiteBuildSessionStatus: Lifecycle state machine for build sessions.
- WebsiteBuildArtifactType: Explicit and extensible categories of build artifacts.
- WebsiteBuildSession: Controlled build workspace session anchored to a Project and Approved PRD.
- WebsiteBuildArtifact: Structural reference records tracking build artifacts.

SECURITY & BOUNDARIES:
- Phase 6.1 establishes ONLY the build session abstraction and controlled workspace.
- ZERO AI website generation, code generation, HTML/CSS generation, GitHub, or Vercel actions.
- Owner isolation enforced via owner_id matching authenticated JWT subject.
"""
from __future__ import annotations

import enum
from datetime import datetime
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


# ── Enums ─────────────────────────────────────────────────────────────────────

class WebsiteBuildSessionStatus(str, enum.Enum):
    """
    Lifecycle states for an AI Website Builder session.

    State Machine (Phase 6.1):
      CREATED -> PLANNED
      CREATED -> CANCELLED
      PLANNED -> READY
      PLANNED -> CANCELLED
      READY -> IN_PROGRESS
      READY -> CANCELLED
      IN_PROGRESS -> PAUSED
      IN_PROGRESS -> COMPLETED
      IN_PROGRESS -> FAILED
      PAUSED -> IN_PROGRESS
      PAUSED -> CANCELLED

    Terminal states (immutable):
      COMPLETED, CANCELLED, FAILED
    """
    CREATED     = "created"
    PLANNED     = "planned"
    READY       = "ready"
    IN_PROGRESS = "in_progress"
    PAUSED      = "paused"
    FAILED      = "failed"
    COMPLETED   = "completed"
    CANCELLED   = "cancelled"


ACTIVE_BUILD_STATUSES = {
    WebsiteBuildSessionStatus.CREATED,
    WebsiteBuildSessionStatus.PLANNED,
    WebsiteBuildSessionStatus.READY,
    WebsiteBuildSessionStatus.IN_PROGRESS,
    WebsiteBuildSessionStatus.PAUSED,
}

TERMINAL_BUILD_STATUSES = {
    WebsiteBuildSessionStatus.FAILED,
    WebsiteBuildSessionStatus.COMPLETED,
    WebsiteBuildSessionStatus.CANCELLED,
}


class WebsiteBuildArtifactType(str, enum.Enum):
    """
    Extensible artifact categories for the AI Website Builder.
    In Phase 6.1, SOURCE_CODE is NOT created automatically.
    """
    PRD_SNAPSHOT          = "prd_snapshot"
    WEBSITE_SPECIFICATION = "website_specification"
    DESIGN_BLUEPRINT      = "design_blueprint"
    DESIGN_PLAN           = "design_plan"
    CONTENT_PLAN          = "content_plan"
    SITE_STRUCTURE        = "site_structure"
    COMPONENT_PLAN        = "component_plan"
    SOURCE_CODE           = "source_code"
    WEBSITE_SOURCE_CODE   = "website_source_code"
    ASSET                 = "asset"
    BUILD_LOG             = "build_log"
    QA_REPORT             = "qa_report"


class WebsiteGenerationStatus(str, enum.Enum):
    """
    Lifecycle status of an AI website specification generation attempt.
    """
    PENDING     = "pending"
    GENERATING  = "generating"
    VALIDATING  = "validating"
    COMPLETED   = "completed"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


class DesignBlueprintStatus(str, enum.Enum):
    """
    Lifecycle status of a Phase 6.3 Design System and Site Architecture Blueprint generation.
    """
    PENDING     = "pending"
    GENERATING  = "generating"
    VALIDATING  = "validating"
    COMPLETED   = "completed"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


class WebsiteCodeGenerationStatus(str, enum.Enum):
    """
    Lifecycle status of a Phase 6.4 Website Source Code Generation execution.
    """
    PENDING     = "pending"
    GENERATING  = "generating"
    VALIDATING  = "validating"
    COMPLETED   = "completed"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


class WebsitePreviewStatus(str, enum.Enum):
    """
    Lifecycle status of an isolated live website preview instance.
    """
    CREATED   = "created"
    STARTING  = "starting"
    RUNNING   = "running"
    STOPPING  = "stopping"
    STOPPED   = "stopped"
    FAILED    = "failed"
    EXPIRED   = "expired"


class WebsiteEditSessionStatus(str, enum.Enum):
    """
    Lifecycle status of an owner iterative website edit request.
    """
    PENDING     = "pending"
    ANALYZING   = "analyzing"
    GENERATING  = "generating"
    VALIDATING  = "validating"
    APPLIED     = "applied"
    FAILED      = "failed"
    CANCELLED   = "cancelled"


# ── Models ────────────────────────────────────────────────────────────────────

class WebsiteBuildSession(UUIDPKMixin, TimestampMixin, Base):
    """
    Controlled build session workspace for a Project.
    Anchored to an approved PRD with exact version preservation.
    """
    __tablename__ = "website_build_sessions"
    __table_args__ = (
        Index("ix_build_sessions_project_id", "project_id"),
        Index("ix_build_sessions_owner_id", "owner_id"),
        Index("ix_build_sessions_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[WebsiteBuildSessionStatus] = mapped_column(
        Enum(WebsiteBuildSessionStatus, name="website_build_session_status", native_enum=False),
        default=WebsiteBuildSessionStatus.CREATED,
        nullable=False,
    )
    build_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    build_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    project: Mapped["Project"] = relationship(lazy="select")
    artifacts: Mapped[List["WebsiteBuildArtifact"]] = relationship(
        back_populates="build_session",
        cascade="all, delete-orphan",
        lazy="select",
    )
    generations: Mapped[List["WebsiteGeneration"]] = relationship(
        back_populates="build_session",
        cascade="all, delete-orphan",
        lazy="select",
    )
    code_generations: Mapped[List["WebsiteCodeGeneration"]] = relationship(
        back_populates="build_session",
        cascade="all, delete-orphan",
        lazy="select",
    )
    previews: Mapped[List["WebsitePreview"]] = relationship(
        back_populates="build_session",
        cascade="all, delete-orphan",
        lazy="select",
    )


class WebsiteBuildArtifact(UUIDPKMixin, TimestampMixin, Base):
    """
    Storage and reference abstraction for build session artifacts.
    """
    __tablename__ = "website_build_artifacts"
    __table_args__ = (
        Index("ix_build_artifacts_session_id", "build_session_id"),
        Index("ix_build_artifacts_project_id", "project_id"),
        Index("ix_build_artifacts_type", "artifact_type"),
    )

    build_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_build_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_type: Mapped[WebsiteBuildArtifactType] = mapped_column(
        Enum(WebsiteBuildArtifactType, name="website_build_artifact_type", native_enum=False),
        nullable=False,
    )
    artifact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content_reference: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    artifact_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    build_session: Mapped["WebsiteBuildSession"] = relationship(
        back_populates="artifacts",
        lazy="select",
    )
    project: Mapped["Project"] = relationship(lazy="select")


class WebsiteGeneration(UUIDPKMixin, TimestampMixin, Base):
    """
    Record of an AI Website Generation execution attempting to produce a
    structured WebsiteSpecification.
    """
    __tablename__ = "website_generations"
    __table_args__ = (
        Index("ix_website_generations_session_id", "build_session_id"),
        Index("ix_website_generations_project_id", "project_id"),
        Index("ix_website_generations_owner_id", "owner_id"),
        Index("ix_website_generations_status", "status"),
    )

    build_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_build_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_prd_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_prds.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_prd_version: Mapped[int] = mapped_column(Integer, nullable=False)
    generation_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[WebsiteGenerationStatus] = mapped_column(
        Enum(WebsiteGenerationStatus, name="website_generation_status", native_enum=False),
        default=WebsiteGenerationStatus.PENDING,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    specification_artifact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_build_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    generation_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    build_session: Mapped["WebsiteBuildSession"] = relationship(
        back_populates="generations",
        lazy="select",
    )
    project: Mapped["Project"] = relationship(lazy="select")
    specification_artifact: Mapped[Optional["WebsiteBuildArtifact"]] = relationship(lazy="select")
    blueprints: Mapped[List["DesignBlueprint"]] = relationship(
        back_populates="source_generation",
        cascade="all, delete-orphan",
        lazy="select",
    )


class DesignBlueprint(UUIDPKMixin, TimestampMixin, Base):
    """
    Phase 6 Stage 6.3 — Design System + Site Architecture Blueprint.
    Structured implementation-ready blueprint mapping tokens, component taxonomy,
    page architecture, responsive behavior, asset requirements, and accessibility rules.
    """
    __tablename__ = "design_blueprints"
    __table_args__ = (
        Index("ix_design_blueprints_generation_id", "source_generation_id"),
        Index("ix_design_blueprints_session_id", "build_session_id"),
        Index("ix_design_blueprints_project_id", "project_id"),
        Index("ix_design_blueprints_owner_id", "owner_id"),
        Index("ix_design_blueprints_status", "status"),
    )

    build_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_build_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_generation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    blueprint_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[DesignBlueprintStatus] = mapped_column(
        Enum(DesignBlueprintStatus, name="design_blueprint_status", native_enum=False),
        default=DesignBlueprintStatus.PENDING,
        nullable=False,
    )
    specification_artifact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_build_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    blueprint_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    build_session: Mapped["WebsiteBuildSession"] = relationship(lazy="select")
    project: Mapped["Project"] = relationship(lazy="select")
    source_generation: Mapped["WebsiteGeneration"] = relationship(back_populates="blueprints", lazy="select")
    specification_artifact: Mapped[Optional["WebsiteBuildArtifact"]] = relationship(lazy="select")
    code_generations: Mapped[List["WebsiteCodeGeneration"]] = relationship(
        back_populates="design_blueprint",
        cascade="all, delete-orphan",
        lazy="select",
    )


class WebsiteCodeGeneration(UUIDPKMixin, TimestampMixin, Base):
    """
    Phase 6 Stage 6.4 — Actual Website Code Generation.
    Executes production-oriented Next.js + React + TypeScript code generation
    from an approved DesignBlueprint, storing structured, validated source code artifacts.
    """
    __tablename__ = "website_code_generations"
    __table_args__ = (
        Index("ix_code_generations_session_id", "build_session_id"),
        Index("ix_code_generations_project_id", "project_id"),
        Index("ix_code_generations_blueprint_id", "design_blueprint_id"),
        Index("ix_code_generations_generation_id", "website_generation_id"),
        Index("ix_code_generations_owner_id", "owner_id"),
        Index("ix_code_generations_status", "status"),
    )

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
    website_generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    design_blueprint_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("design_blueprints.id", ondelete="CASCADE"),
        nullable=False,
    )
    approved_prd_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("client_prds.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_artifact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_build_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    prd_version: Mapped[int] = mapped_column(Integer, nullable=False)
    code_generation_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[WebsiteCodeGenerationStatus] = mapped_column(
        Enum(WebsiteCodeGenerationStatus, name="website_code_generation_status", native_enum=False),
        default=WebsiteCodeGenerationStatus.PENDING,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(100), default="mock_code_provider", nullable=False)
    model: Mapped[str] = mapped_column(String(100), default="mock-nextjs-code-v1", nullable=False)
    source_checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    file_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    generation_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    build_session: Mapped["WebsiteBuildSession"] = relationship(back_populates="code_generations", lazy="select")
    project: Mapped["Project"] = relationship(lazy="select")
    website_generation: Mapped["WebsiteGeneration"] = relationship(lazy="select")
    design_blueprint: Mapped["DesignBlueprint"] = relationship(back_populates="code_generations", lazy="select")
    source_artifact: Mapped[Optional["WebsiteBuildArtifact"]] = relationship(lazy="select")
    previews: Mapped[List["WebsitePreview"]] = relationship(
        back_populates="code_generation",
        cascade="all, delete-orphan",
        lazy="select",
    )
    edit_versions: Mapped[List["WebsiteEditVersion"]] = relationship(
        back_populates="source_generation",
        cascade="all, delete-orphan",
        lazy="select",
    )
    edit_sessions: Mapped[List["WebsiteEditSession"]] = relationship(
        back_populates="base_code_generation",
        cascade="all, delete-orphan",
        lazy="select",
    )


class WebsitePreview(UUIDPKMixin, TimestampMixin, Base):
    """
    Phase 6 Stage 6.5 — Isolated Live Website Preview Instance.
    Maintains the lifecycle and secure runtime reference for an isolated Next.js preview workspace.
    """
    __tablename__ = "website_previews"
    __table_args__ = (
        Index("ix_website_previews_project_id", "project_id"),
        Index("ix_website_previews_session_id", "build_session_id"),
        Index("ix_website_previews_code_generation_id", "code_generation_id"),
        Index("ix_website_previews_token", "preview_token", unique=True),
        Index("ix_website_previews_owner_id", "owner_id"),
        Index("ix_website_previews_status", "status"),
    )

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
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[WebsitePreviewStatus] = mapped_column(
        Enum(WebsitePreviewStatus, name="website_preview_status", native_enum=False),
        default=WebsitePreviewStatus.CREATED,
        nullable=False,
    )
    preview_token: Mapped[str] = mapped_column(String(64), nullable=False)
    port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    process_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    workspace_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    preview_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    project: Mapped["Project"] = relationship(lazy="select")
    build_session: Mapped["WebsiteBuildSession"] = relationship(back_populates="previews", lazy="select")
    code_generation: Mapped["WebsiteCodeGeneration"] = relationship(back_populates="previews", lazy="select")
    edit_sessions: Mapped[List["WebsiteEditSession"]] = relationship(
        back_populates="preview",
        lazy="select",
    )


class WebsiteEditSession(UUIDPKMixin, TimestampMixin, Base):
    """
    Phase 6 Stage 6.5 — Iterative Website Edit Session.
    Tracks an owner's request to modify the website codebase and records analysis and execution state.
    """
    __tablename__ = "website_edit_sessions"
    __table_args__ = (
        Index("ix_website_edit_sessions_project_id", "project_id"),
        Index("ix_website_edit_sessions_preview_id", "preview_id"),
        Index("ix_website_edit_sessions_base_generation_id", "base_code_generation_id"),
        Index("ix_website_edit_sessions_owner_id", "owner_id"),
        Index("ix_website_edit_sessions_status", "status"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    preview_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_previews.id", ondelete="SET NULL"),
        nullable=True,
    )
    base_code_generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_code_generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    base_version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[WebsiteEditSessionStatus] = mapped_column(
        Enum(WebsiteEditSessionStatus, name="website_edit_session_status", native_enum=False),
        default=WebsiteEditSessionStatus.PENDING,
        nullable=False,
    )
    owner_request: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edit_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    project: Mapped["Project"] = relationship(lazy="select")
    preview: Mapped[Optional["WebsitePreview"]] = relationship(back_populates="edit_sessions", lazy="select")
    base_code_generation: Mapped["WebsiteCodeGeneration"] = relationship(back_populates="edit_sessions", lazy="select")
    version_records: Mapped[List["WebsiteEditVersion"]] = relationship(
        back_populates="edit_session",
        lazy="select",
    )


class WebsiteEditVersion(UUIDPKMixin, TimestampMixin, Base):
    """
    Phase 6 Stage 6.5 — Immutable Website Edit Version Record.
    Every applied edit or rollback creates an immutable sequential version record.
    """
    __tablename__ = "website_edit_versions"
    __table_args__ = (
        Index("ix_website_edit_versions_project_id", "project_id"),
        Index("ix_website_edit_versions_session_id", "edit_session_id"),
        Index("ix_website_edit_versions_generation_id", "source_generation_id"),
        Index("ix_website_edit_versions_version", "project_id", "version"),
        Index("ix_website_edit_versions_owner_id", "owner_id"),
        Index("ix_website_edit_versions_is_active", "is_active"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    edit_session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_edit_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_code_generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    parent_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    changed_files: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)
    diff_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_build_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    project: Mapped["Project"] = relationship(lazy="select")
    edit_session: Mapped[Optional["WebsiteEditSession"]] = relationship(back_populates="version_records", lazy="select")
    source_generation: Mapped["WebsiteCodeGeneration"] = relationship(back_populates="edit_versions", lazy="select")
    artifact: Mapped[Optional["WebsiteBuildArtifact"]] = relationship(lazy="select")
