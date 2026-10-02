"""
Follow-up Scheduler Foundation Service.

RESPONSIBILITIES:
- Deterministically identifies follow-up steps that have reached their scheduled_at threshold.
- Evaluates eligibility via FollowUpEligibilityService.
- Updates step readiness without executing any sending actions.

STRICT SAFETY GUARANTEES:
- Strictly NO email sending.
- Strictly NO Gmail API invocation.
- Strictly NO background worker or cron auto-dispatch in Stage 4.4.
- Fails closed on any ineligibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from models import Lead
from models.follow_up import (
    FollowUpSequence,
    FollowUpSequenceStatus,
    FollowUpStep,
    FollowUpStepStatus,
    FollowUpStopReason,
)
from models.outreach import OutreachMessage
from services.follow_up_eligibility_service import (
    FollowUpEligibilityResult,
    FollowUpEligibilityService,
)

log = structlog.get_logger(__name__)


@dataclass
class DueFollowUpStep:
    """Represents a scheduled follow-up step that is currently due and eligible for preparation."""
    sequence_id: uuid.UUID
    step_id: uuid.UUID
    step_number: int
    scheduled_at: datetime
    lead_id: uuid.UUID
    recipient_email: str
    original_message_id: uuid.UUID
    eligibility: FollowUpEligibilityResult


class FollowUpSchedulerService:
    """
    Scheduler interface for finding due follow-up steps.
    """

    def __init__(self, eligibility_service: Optional[FollowUpEligibilityService] = None):
        self._eligibility_service = eligibility_service or FollowUpEligibilityService()

    async def find_due_follow_up_steps(
        self,
        db: AsyncSession,
        now: Optional[datetime] = None,
    ) -> List[DueFollowUpStep]:
        """
        Scan active follow-up sequences where next_action_at <= now,
        evaluate eligibility, and return all eligible due steps.
        
        Does NOT send emails. Does NOT call Gmail API.
        """
        ref_time = now or datetime.now(timezone.utc)
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        # 1. Query active sequences due by ref_time
        stmt = (
            select(FollowUpSequence)
            .where(
                FollowUpSequence.status == FollowUpSequenceStatus.ACTIVE,
                FollowUpSequence.next_action_at <= ref_time,
            )
            .order_by(FollowUpSequence.next_action_at.asc())
        )
        res = await db.execute(stmt)
        sequences = res.scalars().all()

        due_steps: List[DueFollowUpStep] = []

        for seq in sequences:
            # 2. Find current step
            step_stmt = (
                select(FollowUpStep)
                .where(
                    FollowUpStep.sequence_id == seq.id,
                    FollowUpStep.step_number == seq.current_step,
                    FollowUpStep.status.in_([FollowUpStepStatus.PENDING, FollowUpStepStatus.READY]),
                )
            )
            step = await db.scalar(step_stmt)
            if not step:
                # If current step is already sent or completed, check if max steps reached
                if seq.current_step > seq.max_steps:
                    seq.status = FollowUpSequenceStatus.COMPLETED
                    seq.next_action_at = None
                    await db.commit()
                continue

            # Verify step scheduled_at has arrived
            step_scheduled = step.scheduled_at
            if step_scheduled.tzinfo is None:
                step_scheduled = step_scheduled.replace(tzinfo=timezone.utc)

            if step_scheduled > ref_time:
                # Update sequence next_action_at to match step scheduled_at
                seq.next_action_at = step_scheduled
                await db.commit()
                continue

            # 3. Evaluate eligibility
            eligibility = await self._eligibility_service.evaluate_sequence_eligibility(
                db, sequence=seq, step=step
            )

            if not eligibility.eligible:
                log.info(
                    "Follow-up step due but ineligible",
                    sequence_id=str(seq.id),
                    step_number=step.step_number,
                    reason=eligibility.reason,
                )
                # If suppression violation detected, stop sequence automatically
                if "suppression" in (eligibility.reason or "").lower():
                    seq.status = FollowUpSequenceStatus.STOPPED
                    seq.stopped_at = ref_time
                    seq.stop_reason = FollowUpStopReason.SUPPRESSED
                    seq.next_action_at = None
                    step.status = FollowUpStepStatus.CANCELLED
                    await db.commit()
                continue

            # 4. Mark step as READY if it was PENDING
            if step.status == FollowUpStepStatus.PENDING:
                step.status = FollowUpStepStatus.READY
                await db.commit()

            # 5. Fetch recipient email from original message
            orig_msg = await db.scalar(
                select(OutreachMessage).where(OutreachMessage.id == seq.original_message_id)
            )
            recipient_email = orig_msg.recipient_email if orig_msg else ""

            due_steps.append(
                DueFollowUpStep(
                    sequence_id=seq.id,
                    step_id=step.id,
                    step_number=step.step_number,
                    scheduled_at=step_scheduled,
                    lead_id=seq.lead_id,
                    recipient_email=recipient_email,
                    original_message_id=seq.original_message_id,
                    eligibility=eligibility,
                )
            )

        return due_steps
