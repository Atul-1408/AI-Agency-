"""
Core Follow-up Sequence Management Service.

Handles:
- Sequence creation from sent OutreachMessage
- Duplicate active sequence protection
- Controlled state transitions: ACTIVE -> PAUSED -> ACTIVE, or STOPPED/COMPLETED
- Step cancellation on stop
- Immutable audit logging in agent_runs
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Sequence
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from models import AgentRun, AgentRunStatus, Lead
from models.follow_up import (
    FollowUpSequence,
    FollowUpSequenceStatus,
    FollowUpStep,
    FollowUpStepStatus,
    FollowUpStopReason,
)
from models.outreach import OutreachMessage, OutreachMessageStatus
from schemas.follow_up import CadenceStepConfig
from services.follow_up_cadence import calculate_cadence_schedule

log = structlog.get_logger(__name__)


class FollowUpServiceError(Exception):
    """Base exception for follow-up sequence operations."""
    pass


class SequenceNotFoundError(FollowUpServiceError):
    """Raised when sequence is not found."""
    pass


class InvalidMessageError(FollowUpServiceError):
    """Raised when the outreach message is invalid or not sent."""
    pass


class DuplicateActiveSequenceError(FollowUpServiceError):
    """Raised when an active sequence already exists for this outreach message."""
    pass


class InvalidStateTransitionError(FollowUpServiceError):
    """Raised when an invalid sequence state transition is attempted."""
    pass


class FollowUpService:
    """
    Manages the lifecycle of FollowUpSequence entities and their child FollowUpStep records.
    """

    async def create_sequence(
        self,
        db: AsyncSession,
        original_message_id: uuid.UUID,
        cadence: Optional[List[CadenceStepConfig]] = None,
        owner_id: str = "system",
    ) -> FollowUpSequence:
        """
        Create a new follow-up sequence anchored to a sent outreach message.
        """
        # 1. Verify original outreach message exists and is SENT
        orig_msg = await db.scalar(
            select(OutreachMessage).where(OutreachMessage.id == original_message_id)
        )
        if not orig_msg:
            raise InvalidMessageError(f"Original outreach message {original_message_id} not found.")

        if orig_msg.status != OutreachMessageStatus.SENT:
            raise InvalidMessageError(
                f"Cannot create follow-up sequence: original message status is '{orig_msg.status.value}', expected 'sent'."
            )

        # 2. Prevent duplicate active sequences for this outreach message
        existing_active = await db.scalar(
            select(FollowUpSequence).where(
                FollowUpSequence.original_message_id == original_message_id,
                FollowUpSequence.status == FollowUpSequenceStatus.ACTIVE,
            )
        )
        if existing_active:
            raise DuplicateActiveSequenceError(
                f"An active follow-up sequence ({existing_active.id}) already exists for message {original_message_id}."
            )

        # 3. Calculate step plan using cadence configuration
        base_time = orig_msg.sent_at or datetime.now(timezone.utc)
        step_plans = calculate_cadence_schedule(base_time=base_time, cadence_steps=cadence)

        now = datetime.now(timezone.utc)
        first_step_time = step_plans[0].scheduled_at if step_plans else None

        # 4. Create sequence
        sequence = FollowUpSequence(
            lead_id=orig_msg.lead_id,
            outreach_draft_id=orig_msg.draft_id,
            original_message_id=orig_msg.id,
            status=FollowUpSequenceStatus.ACTIVE,
            current_step=1,
            max_steps=len(step_plans),
            next_action_at=first_step_time,
        )
        db.add(sequence)
        await db.flush()

        # 5. Create child steps
        created_steps: List[FollowUpStep] = []
        for plan_item in step_plans:
            step = FollowUpStep(
                sequence_id=sequence.id,
                step_number=plan_item.step_number,
                delay_hours=plan_item.delay_hours,
                status=FollowUpStepStatus.PENDING,
                scheduled_at=plan_item.scheduled_at,
            )
            db.add(step)
            created_steps.append(step)

        await db.flush()

        # 6. Audit logging
        audit_seq = AgentRun(
            agent_name="follow_up",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "action": "followup_sequence_created",
                "sequence_id": str(sequence.id),
                "lead_id": str(sequence.lead_id),
                "original_message_id": str(orig_msg.id),
                "max_steps": len(step_plans),
                "next_action_at": first_step_time.isoformat() if first_step_time else None,
                "owner": owner_id,
            },
            started_at=now,
            completed_at=now,
        )
        db.add(audit_seq)

        for step in created_steps:
            audit_step = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.COMPLETED,
                input_data={
                    "action": "followup_step_scheduled",
                    "sequence_id": str(sequence.id),
                    "step_id": str(step.id),
                    "step_number": step.step_number,
                    "delay_hours": step.delay_hours,
                    "scheduled_at": step.scheduled_at.isoformat(),
                    "owner": owner_id,
                },
                started_at=now,
                completed_at=now,
            )
            db.add(audit_step)

        await db.commit()
        await db.refresh(sequence)
        return sequence

    async def pause_sequence(
        self,
        db: AsyncSession,
        sequence_id: uuid.UUID,
        owner_id: str = "system",
    ) -> FollowUpSequence:
        """Pause an ACTIVE follow-up sequence."""
        stmt = select(FollowUpSequence).where(FollowUpSequence.id == sequence_id).with_for_update()
        seq = await db.scalar(stmt)
        if not seq:
            raise SequenceNotFoundError(f"Follow-up sequence {sequence_id} not found.")

        if seq.status != FollowUpSequenceStatus.ACTIVE:
            raise InvalidStateTransitionError(
                f"Cannot pause sequence with status '{seq.status.value}'. Only 'active' sequences can be paused."
            )

        seq.status = FollowUpSequenceStatus.PAUSED
        now = datetime.now(timezone.utc)

        audit = AgentRun(
            agent_name="follow_up",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "action": "followup_sequence_paused",
                "sequence_id": str(seq.id),
                "owner": owner_id,
            },
            started_at=now,
            completed_at=now,
        )
        db.add(audit)
        await db.commit()
        await db.refresh(seq)
        return seq

    async def resume_sequence(
        self,
        db: AsyncSession,
        sequence_id: uuid.UUID,
        owner_id: str = "system",
    ) -> FollowUpSequence:
        """Resume a PAUSED follow-up sequence back to ACTIVE."""
        stmt = select(FollowUpSequence).where(FollowUpSequence.id == sequence_id).with_for_update()
        seq = await db.scalar(stmt)
        if not seq:
            raise SequenceNotFoundError(f"Follow-up sequence {sequence_id} not found.")

        if seq.status != FollowUpSequenceStatus.PAUSED:
            raise InvalidStateTransitionError(
                f"Cannot resume sequence with status '{seq.status.value}'. Only 'paused' sequences can be resumed."
            )

        seq.status = FollowUpSequenceStatus.ACTIVE
        now = datetime.now(timezone.utc)

        audit = AgentRun(
            agent_name="follow_up",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "action": "followup_sequence_resumed",
                "sequence_id": str(seq.id),
                "owner": owner_id,
            },
            started_at=now,
            completed_at=now,
        )
        db.add(audit)
        await db.commit()
        await db.refresh(seq)
        return seq

    async def stop_sequence(
        self,
        db: AsyncSession,
        sequence_id: uuid.UUID,
        reason: FollowUpStopReason = FollowUpStopReason.OWNER_STOPPED,
        notes: Optional[str] = None,
        owner_id: str = "system",
    ) -> FollowUpSequence:
        """Stop a sequence permanently and cancel any pending child steps."""
        stmt = select(FollowUpSequence).where(FollowUpSequence.id == sequence_id).with_for_update()
        seq = await db.scalar(stmt)
        if not seq:
            raise SequenceNotFoundError(f"Follow-up sequence {sequence_id} not found.")

        if seq.status in (FollowUpSequenceStatus.STOPPED, FollowUpSequenceStatus.COMPLETED):
            raise InvalidStateTransitionError(
                f"Sequence is already '{seq.status.value}' and cannot be stopped again."
            )

        now = datetime.now(timezone.utc)
        seq.status = FollowUpSequenceStatus.STOPPED
        seq.stopped_at = now
        seq.stop_reason = reason
        seq.next_action_at = None

        # Cancel pending/ready steps
        steps_stmt = select(FollowUpStep).where(
            FollowUpStep.sequence_id == seq.id,
            FollowUpStep.status.in_([FollowUpStepStatus.PENDING, FollowUpStepStatus.READY]),
        )
        steps_res = await db.execute(steps_stmt)
        steps = steps_res.scalars().all()

        cancelled_count = 0
        for step in steps:
            step.status = FollowUpStepStatus.CANCELLED
            cancelled_count += 1
            audit_step_cancel = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.COMPLETED,
                input_data={
                    "action": "followup_step_cancelled",
                    "sequence_id": str(seq.id),
                    "step_id": str(step.id),
                    "step_number": step.step_number,
                    "reason": reason.value,
                    "owner": owner_id,
                },
                started_at=now,
                completed_at=now,
            )
            db.add(audit_step_cancel)

        audit_seq_stop = AgentRun(
            agent_name="follow_up",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "action": "followup_sequence_stopped",
                "sequence_id": str(seq.id),
                "stop_reason": reason.value,
                "notes": notes,
                "cancelled_steps": cancelled_count,
                "owner": owner_id,
            },
            started_at=now,
            completed_at=now,
        )
        db.add(audit_seq_stop)

        await db.commit()
        await db.refresh(seq)
        return seq
