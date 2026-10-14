"""
Phase 7 — Automated Website QA & Evaluator Models.

Entities defined:
- WebsiteQARunStatus: Lifecycle state machine for QA runs.
- QAFindingSeverity: Severity levels for QA findings (BLOCKER, HIGH, MEDIUM, LOW, INFO).
- QAFindingCategory: Defect and quality check categories.
- WebsiteQARun: Orchestrated QA execution anchored to a Project, Build Session, and Target Version.
- WebsiteQAFinding: Structured defect or warning record with evidence, affected routes, and proposed repairs.
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


# ── Enums ─────────────────────────────────────────────────────────────────────

class WebsiteQARunStatus(str, enum.Enum):
    """
    Lifecycle status of an automated website QA run.
    """
    READY_FOR_QA         = "ready_for_qa"
    RUNNING              = "running"
    PASSED               = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED               = "failed"
    CANCELLED            = "cancelled"


class QAFindingSeverity(str, enum.Enum):
    """
    Severity rating for website defects detected during QA.
    BLOCKER / HIGH prevent deployment.
    """
    BLOCKER = "blocker"
    HIGH    = "high"
    MEDIUM  = "medium"
    LOW     = "low"
    INFO    = "info"


class QAFindingCategory(str, enum.Enum):
    """
    Categorization of automated QA checks.
    """
    BUILD_INTEGRITY    = "build_integrity"
    ROUTING            = "routing"
    BROKEN_LINKS       = "broken_links"
    VIEWPORT_OVERFLOW  = "viewport_overflow"
    ACCESSIBILITY      = "accessibility"
    SEO                = "seo"
    SECURITY_SECRETS   = "security_secrets"
    PERFORMANCE        = "performance"


# ── Models ────────────────────────────────────────────────────────────────────

class WebsiteQARun(UUIDPKMixin, TimestampMixin, Base):
    """
    Phase 7 — Automated QA Run.
    Anchored to a Project, BuildSession, and exact Code Generation/Version.
    """
    __tablename__ = "website_qa_runs"
    __table_args__ = (
        Index("ix_qa_runs_project_id", "project_id"),
        Index("ix_qa_runs_session_id", "build_session_id"),
        Index("ix_qa_runs_generation_id", "source_generation_id"),
        Index("ix_qa_runs_owner_id", "owner_id"),
        Index("ix_qa_runs_status", "status"),
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
    source_generation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_code_generations.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[WebsiteQARunStatus] = mapped_column(
        Enum(WebsiteQARunStatus, name="website_qa_run_status", native_enum=False),
        default=WebsiteQARunStatus.READY_FOR_QA,
        nullable=False,
    )
    total_checks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_checks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_checks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    warning_checks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_checks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    run_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    project: Mapped["Project"] = relationship(lazy="select")
    build_session: Mapped["WebsiteBuildSession"] = relationship(lazy="select")
    code_generation: Mapped["WebsiteCodeGeneration"] = relationship(lazy="select")
    findings: Mapped[List["WebsiteQAFinding"]] = relationship(
        back_populates="qa_run",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="WebsiteQAFinding.severity",
    )


class WebsiteQAFinding(UUIDPKMixin, TimestampMixin, Base):
    """
    Phase 7 — QA Defect or Finding Record.
    Captures specific defect, evidence, affected route, and proposed repair instruction.
    """
    __tablename__ = "website_qa_findings"
    __table_args__ = (
        Index("ix_qa_findings_run_id", "qa_run_id"),
        Index("ix_qa_findings_project_id", "project_id"),
        Index("ix_qa_findings_severity", "severity"),
        Index("ix_qa_findings_category", "category"),
        Index("ix_qa_findings_is_repaired", "is_repaired"),
    )

    qa_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("website_qa_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[QAFindingSeverity] = mapped_column(
        Enum(QAFindingSeverity, name="qa_finding_severity", native_enum=False),
        nullable=False,
    )
    category: Mapped[QAFindingCategory] = mapped_column(
        Enum(QAFindingCategory, name="qa_finding_category", native_enum=False),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_route: Mapped[str] = mapped_column(String(255), default="/", nullable=False)
    affected_file: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reproduction_steps: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggested_repair: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_repaired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    repaired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    repaired_in_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    finding_metadata: Mapped[Dict[str, Any]] = mapped_column("metadata", JSON, default=dict, nullable=False)

    # Relationships
    qa_run: Mapped["WebsiteQARun"] = relationship(back_populates="findings", lazy="select")
    project: Mapped["Project"] = relationship(lazy="select")
