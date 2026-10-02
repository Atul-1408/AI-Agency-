"""
Reply Detection Service Boundary for Phase 4.

RESPONSIBILITIES:
- Encapsulates the contract for handling detected incoming prospect replies.
- Stops follow-up sequences immediately upon reply detection.
- Cancels all pending/ready steps in the sequence.
- Records stop_reason = REPLIED.
- Logs an immutable audit event in agent_runs.

IMPORTANT:
- No Gmail inbox reading or polling is implemented in Stage 4.4.
- Actual Google Gmail thread/message inspection will be connected in a dedicated future stage.
- Strictly NO mock production replies or synthetic inbox fake loops.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from models import AgentRun, AgentRunStatus
from models.follow_up import (
    FollowUpSequence,
    FollowUpSequenceStatus,
    FollowUpStep,
    FollowUpStepStatus,
    FollowUpStopReason,
)

log = structlog.get_logger(__name__)


class SequenceNotFoundError(Exception):
    """Raised when the specified sequence does not exist."""
    pass


class SequenceAlreadyTerminatedError(Exception):
    """Raised when trying to terminate an already stopped sequence."""
    pass


class ReplyDetectionService:
    """
    Contract interface for processing verified prospect replies and terminating follow-up sequences.
    """

    async def handle_reply_detected(
        self,
        db: AsyncSession,
        sequence_id: uuid.UUID,
        detected_at: Optional[datetime] = None,
        gmail_message_id: Optional[str] = None,
        snippet: Optional[str] = None,
        owner_id: str = "system",
    ) -> FollowUpSequence:
        """
        Record a detected reply on a sequence:
        1. Transitions sequence to STOPPED with stop_reason = REPLIED.
        2. Cancels all child steps that are PENDING or READY.
        3. Clears next_action_at.
        4. Logs 'reply_detected' and 'followup_sequence_stopped' in agent_runs.
        """
        now = detected_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        stmt = select(FollowUpSequence).where(FollowUpSequence.id == sequence_id).with_for_update()
        sequence = await db.scalar(stmt)
        if not sequence:
            raise SequenceNotFoundError(f"Follow-up sequence {sequence_id} does not exist.")

        # Update sequence
        prev_status = sequence.status
        sequence.status = FollowUpSequenceStatus.STOPPED
        sequence.stopped_at = now
        sequence.stop_reason = FollowUpStopReason.REPLIED
        sequence.next_action_at = None

        # Cancel all pending/ready steps
        steps_stmt = select(FollowUpStep).where(
            FollowUpStep.sequence_id == sequence.id,
            FollowUpStep.status.in_([FollowUpStepStatus.PENDING, FollowUpStepStatus.READY]),
        )
        steps_res = await db.execute(steps_stmt)
        steps = steps_res.scalars().all()

        cancelled_count = 0
        for step in steps:
            step.status = FollowUpStepStatus.CANCELLED
            cancelled_count += 1

        # Audit log: reply_detected
        audit_run = AgentRun(
            agent_name="follow_up",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "action": "reply_detected",
                "sequence_id": str(sequence.id),
                "lead_id": str(sequence.lead_id),
                "original_message_id": str(sequence.original_message_id) if sequence.original_message_id else None,
                "gmail_message_id": gmail_message_id,
                "owner": owner_id,
            },
            output_data={
                "previous_status": prev_status.value,
                "new_status": sequence.status.value,
                "stop_reason": sequence.stop_reason.value,
                "cancelled_steps_count": cancelled_count,
            },
            started_at=now,
            completed_at=now,
        )
        db.add(audit_run)

        # Audit log: followup_sequence_stopped
        stop_audit = AgentRun(
            agent_name="follow_up",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "action": "followup_sequence_stopped",
                "sequence_id": str(sequence.id),
                "lead_id": str(sequence.lead_id),
                "stop_reason": FollowUpStopReason.REPLIED.value,
                "owner": owner_id,
            },
            started_at=now,
            completed_at=now,
        )
        db.add(stop_audit)

        await db.commit()
        await db.refresh(sequence)

        log.info(
            "Follow-up sequence stopped due to reply detection",
            sequence_id=str(sequence.id),
            cancelled_steps=cancelled_count,
        )
        return sequence
