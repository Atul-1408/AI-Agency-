"""
Phase 9 Database Models: Agent Workflow & Step Telemetry.

Provides explicit state tracking, execution modes (manual, supervised, dry-run),
gatekeeping pauses, failure recovery, and audit records for the complete
24-stage AI Web Agency pipeline.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from core.database import Base
from models import TimestampMixin, UUIDPKMixin


class WorkflowExecutionMode(str, enum.Enum):
    """Execution mode governing automation level and safety constraints."""
    MANUAL = "manual"          # Owner manually advances each individual stage
    SUPERVISED = "supervised"  # Automates safe steps; pauses unconditionally at human approval gates
    DRY_RUN = "dry_run"        # Pure simulation without external mutations or side-effects


class WorkflowStatus(str, enum.Enum):
    """Lifecycle status of the end-to-end pipeline execution."""
    CREATED = "created"
    RUNNING = "running"
    PAUSED_FOR_APPROVAL = "paused_for_approval"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkflowStage(str, enum.Enum):
    """The 24 canonical stages of the complete agency agent workflow."""
    LEAD_DISCOVERY = "lead_discovery"
    RESEARCH = "research"
    QUALIFICATION = "qualification"
    GATE_1_LEAD_APPROVAL = "gate_1_lead_approval"
    OUTREACH_DRAFT = "outreach_draft"
    GATE_2_OUTREACH_APPROVAL = "gate_2_outreach_approval"
    SAFETY_CHECKS = "safety_checks"
    GMAIL_DISPATCH = "gmail_dispatch"
    REPLY_DETECTION = "reply_detection"
    CLIENT_REQUIREMENTS = "client_requirements"
    REQUIREMENT_REVIEW = "requirement_review"
    PRD_GENERATION = "prd_generation"
    GATE_4_PRD_APPROVAL = "gate_4_prd_approval"
    PROJECT_CREATION = "project_creation"
    WEBSITE_SPECIFICATION = "website_specification"
    DESIGN_BLUEPRINT = "design_blueprint"
    CODE_GENERATION = "code_generation"
    PREVIEW_AND_EDITING = "preview_and_editing"
    WEBSITE_QA = "website_qa"
    REPAIR_AND_RECHECK = "repair_and_recheck"
    GATE_5_DEPLOYMENT_APPROVAL = "gate_5_deployment_approval"
    GITHUB_PUBLISHING = "github_publishing"
    VERCEL_DEPLOYMENT = "vercel_deployment"
    DEPLOYMENT_VERIFICATION = "deployment_verification"


# Canonical sequence of the 24 stages
WORKFLOW_STAGE_ORDER: List[WorkflowStage] = [
    WorkflowStage.LEAD_DISCOVERY,
    WorkflowStage.RESEARCH,
    WorkflowStage.QUALIFICATION,
    WorkflowStage.GATE_1_LEAD_APPROVAL,
    WorkflowStage.OUTREACH_DRAFT,
    WorkflowStage.GATE_2_OUTREACH_APPROVAL,
    WorkflowStage.SAFETY_CHECKS,
    WorkflowStage.GMAIL_DISPATCH,
    WorkflowStage.REPLY_DETECTION,
    WorkflowStage.CLIENT_REQUIREMENTS,
    WorkflowStage.REQUIREMENT_REVIEW,
    WorkflowStage.PRD_GENERATION,
    WorkflowStage.GATE_4_PRD_APPROVAL,
    WorkflowStage.PROJECT_CREATION,
    WorkflowStage.WEBSITE_SPECIFICATION,
    WorkflowStage.DESIGN_BLUEPRINT,
    WorkflowStage.CODE_GENERATION,
    WorkflowStage.PREVIEW_AND_EDITING,
    WorkflowStage.WEBSITE_QA,
    WorkflowStage.REPAIR_AND_RECHECK,
    WorkflowStage.GATE_5_DEPLOYMENT_APPROVAL,
    WorkflowStage.GITHUB_PUBLISHING,
    WorkflowStage.VERCEL_DEPLOYMENT,
    WorkflowStage.DEPLOYMENT_VERIFICATION,
]

# Explicit set of human approval gates
HUMAN_APPROVAL_GATES = {
    WorkflowStage.GATE_1_LEAD_APPROVAL,
    WorkflowStage.GATE_2_OUTREACH_APPROVAL,
    WorkflowStage.GATE_4_PRD_APPROVAL,
    WorkflowStage.GATE_5_DEPLOYMENT_APPROVAL,
}


class AgentWorkflow(UUIDPKMixin, TimestampMixin, Base):
    """
    Central persisted entity for an end-to-end multi-agent workflow.
    Tracks state, mode, current stage, context data, and error states.
    """
    __tablename__ = "agent_workflows"

    owner_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    mode: Mapped[WorkflowExecutionMode] = mapped_column(
        Enum(WorkflowExecutionMode, name="workflow_execution_mode", native_enum=False),
        default=WorkflowExecutionMode.SUPERVISED,
        nullable=False,
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        Enum(WorkflowStatus, name="workflow_status", native_enum=False),
        default=WorkflowStatus.CREATED,
        nullable=False,
        index=True,
    )
    current_stage: Mapped[WorkflowStage] = mapped_column(
        Enum(WorkflowStage, name="workflow_stage", native_enum=False),
        default=WorkflowStage.LEAD_DISCOVERY,
        nullable=False,
        index=True,
    )

    # Completed stage records: list of {"stage": str, "completed_at": str, "duration_ms": int, "output": dict}
    completed_stages: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    # Remaining stage list
    pending_stages: Mapped[List[str]] = mapped_column(JSON, default=list, nullable=False)

    # Consolidated cross-stage context payload
    stage_data: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    # Current approval request when paused at a human gate
    current_approval_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Explicit stage-level error state
    error_state: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)

    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Step records relationship
    step_records: Mapped[List["WorkflowStepRecord"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowStepRecord.created_at.asc()",
        lazy="selectin",
    )


class WorkflowStepRecord(UUIDPKMixin, TimestampMixin, Base):
    """
    Immutable audit log for each individual stage transition in a workflow.
    """
    __tablename__ = "workflow_step_records"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # "started", "completed", "failed", "paused", "skipped"
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    input_snapshot: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    output_snapshot: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    workflow: Mapped["AgentWorkflow"] = relationship(back_populates="step_records")
