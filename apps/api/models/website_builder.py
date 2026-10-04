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
    DESIGN_PLAN           = "design_plan"
    CONTENT_PLAN          = "content_plan"
    SITE_STRUCTURE        = "site_structure"
    COMPONENT_PLAN        = "component_plan"
    SOURCE_CODE           = "source_code"
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
