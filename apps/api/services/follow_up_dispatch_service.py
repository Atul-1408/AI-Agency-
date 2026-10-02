"""
Follow-up Dispatch Service — Phase 4 Stage 4.7.

Implements the authorized send path for a single approved follow-up draft.

RESPONSIBILITIES:
- Verifies sequence and step eligibility via FollowUpEligibilityService
- Performs a final fresh reply check immediately before dispatch to prevent
  sending into a thread where the prospect has already responded
- Delegates to the existing SafetyController for comprehensive authorization
  (quotas, pacing, suppression, MX verification, Gmail health, circuit breaker)
- Delegates to the existing GmailDispatchService for the actual send
- Records OutreachMessage and SendAttempt on success
- Transitions FollowUpStep → SENT and FollowUpSequence → COMPLETED if all
  steps are exhausted
- Never bypasses SafetyController; never calls gmail.send directly
- Produces an immutable audit trail in agent_runs
- Fails closed: any safety or infrastructure failure blocks the send

CONSTRAINTS:
- ONE email per invocation — strictly no bulk or batch dispatch
- No automatic, scheduled, or recurring sending
- No bypass of Gate 2 approval; draft must be APPROVED before this service is called
- No Gmail inbox reading beyond what reply detection already handles
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from models import (
    AgentRun,
    AgentRunStatus,
    Lead,
    LeadStatus,
)
from models.follow_up import (
    FollowUpSequence,
    FollowUpSequenceStatus,
    FollowUpStep,
    FollowUpStepStatus,
    FollowUpStopReason,
    InboundMessage,
)
from models.outreach import (
    GmailAccount,
    GmailConnectionStatus,
    OutreachDraft,
    OutreachDraftStatus,
    OutreachMessage,
    OutreachMessageStatus,
    SendAttempt,
    SendAttemptResult,
)
from services.follow_up_eligibility_service import FollowUpEligibilityService
from services.gmail_dispatch_service import GmailDispatchError, GmailDispatchService
from services.safety_controller import SafetyController

log = structlog.get_logger(__name__)


# ── Domain Exceptions ─────────────────────────────────────────────────────────

class FollowUpDispatchError(Exception):
    """Base exception for follow-up dispatch failures."""
    pass


class FollowUpDispatchSequenceNotFoundError(FollowUpDispatchError):
    """Sequence not found."""
    pass


class FollowUpDispatchStepNotFoundError(FollowUpDispatchError):
    """Step not found within the sequence."""
    pass


class FollowUpDispatchDraftNotFoundError(FollowUpDispatchError):
    """No approved draft is attached to the step."""
    pass


class FollowUpDispatchReplyDetectedError(FollowUpDispatchError):
    """Dispatch blocked because a prospect reply was detected on the thread."""
    pass


class FollowUpDispatchEligibilityError(FollowUpDispatchError):
    """Sequence or step failed eligibility checks."""
    pass


class FollowUpDispatchSafetyError(FollowUpDispatchError):
    """SafetyController blocked the send."""
    pass


class FollowUpDispatchGmailError(FollowUpDispatchError):
    """Gmail API call failed during dispatch."""
    pass


class FollowUpDispatchIdempotentError(FollowUpDispatchError):
    """Step has already been sent (idempotency guard)."""
    pass


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class FollowUpDispatchResult:
    """Safe result object returned after a successful follow-up send."""
    outreach_message_id: uuid.UUID
    send_attempt_id: uuid.UUID
    gmail_message_id: str
    gmail_thread_id: str
    sent_at: datetime
    recipient_email: str
    subject: str
    sequence_id: uuid.UUID
    step_id: uuid.UUID
    step_number: int
    sequence_completed: bool


# ── Service ───────────────────────────────────────────────────────────────────

class FollowUpDispatchService:
    """
    Controlled single-step follow-up email dispatch service.

    The only permitted path:
      FollowUpSequence (ACTIVE)
        → FollowUpStep (PENDING or READY)
          → OutreachDraft (APPROVED, with follow_up_sequence_id + follow_up_step_id)
            → Fresh reply check
              → SafetyController.authorize(...)
                → GmailDispatchService.dispatch_draft(...)
                  → OutreachMessage + SendAttempt recorded
                    → step.status = SENT, sequence advances or COMPLETES
    """

    def __init__(
        self,
        eligibility_service: Optional[FollowUpEligibilityService] = None,
        safety_controller: Optional[SafetyController] = None,
        dispatch_service: Optional[GmailDispatchService] = None,
    ):
        self._eligibility_service = eligibility_service or FollowUpEligibilityService()
        self._safety_controller = safety_controller or SafetyController()
        self._dispatch_service = dispatch_service or GmailDispatchService()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _log_audit(
        self,
        db: AsyncSession,
        action: str,
        owner_id: str,
        run_status: AgentRunStatus,
        input_data: Optional[dict] = None,
        output_data: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> AgentRun:
        """Record an immutable audit entry. Never logs OAuth tokens."""
        _forbidden = {
            "token", "refresh_token", "access_token",
            "client_secret", "code", "encrypted_refresh_token", "key",
        }
        def _sanitize(d: Optional[dict]) -> dict:
            if not d:
                return {}
            return {k: v for k, v in d.items() if k.lower() not in _forbidden}

        now = datetime.now(timezone.utc)
        run = AgentRun(
            agent_name="follow_up_dispatch",
            status=run_status,
            input_data={"action": action, "owner": owner_id, **_sanitize(input_data)},
            output_data=_sanitize(output_data),
            error_message=error_message,
            started_at=now,
            completed_at=now,
        )
        db.add(run)
        await db.flush()
        return run

    async def _fresh_reply_check(
        self,
        db: AsyncSession,
        sequence: FollowUpSequence,
        step: FollowUpStep,
    ) -> bool:
        """
        Inspect the database for any InboundMessage matching this sequence's thread.
        Returns True if a reply is detected (and the sequence should be stopped).
        Does NOT call Gmail API — uses only already-persisted InboundMessage records.
        """
        if not sequence.original_message_id:
            return False

        orig_msg = await db.scalar(
            select(OutreachMessage).where(OutreachMessage.id == sequence.original_message_id)
        )
        if not orig_msg or not orig_msg.gmail_thread_id:
            return False

        reply = await db.scalar(
            select(InboundMessage).where(
                InboundMessage.gmail_thread_id == orig_msg.gmail_thread_id,
                InboundMessage.matched_sequence_id == sequence.id,
            )
        )
        return reply is not None

    async def _advance_or_complete_sequence(
        self,
        db: AsyncSession,
        sequence: FollowUpSequence,
        completed_step: FollowUpStep,
        now: datetime,
    ) -> bool:
        """
        After a successful step send:
        - If there are more PENDING/READY steps → advance sequence.current_step.
        - If no more steps remain → mark sequence COMPLETED.
        Returns True if the sequence was completed.
        """
        remaining_steps = (await db.scalars(
            select(FollowUpStep).where(
                FollowUpStep.sequence_id == sequence.id,
                FollowUpStep.step_number > completed_step.step_number,
                FollowUpStep.status.in_([
                    FollowUpStepStatus.PENDING,
                    FollowUpStepStatus.READY,
                ]),
            )
        )).all()

        if not remaining_steps:
            # All steps exhausted → complete the sequence
            sequence.status = FollowUpSequenceStatus.COMPLETED
            sequence.stop_reason = FollowUpStopReason.MAX_STEPS_REACHED
            sequence.stopped_at = now
            log.info(
                "Follow-up sequence completed — all steps sent",
                sequence_id=str(sequence.id),
                completed_step=completed_step.step_number,
            )
            return True

        # Advance to next step
        next_step = min(remaining_steps, key=lambda s: s.step_number)
        sequence.current_step = next_step.step_number
        sequence.next_action_at = next_step.scheduled_at
        log.info(
            "Follow-up sequence advanced to next step",
            sequence_id=str(sequence.id),
            next_step=next_step.step_number,
        )
        return False

    # ── Main dispatch method ──────────────────────────────────────────────────

    async def dispatch_follow_up_step(
        self,
        db: AsyncSession,
        sequence_id: uuid.UUID,
        step_id: uuid.UUID,
        owner_id: str,
    ) -> FollowUpDispatchResult:
        """
        Dispatch a single approved follow-up draft.

        Pre-dispatch order:
        1. Load and verify sequence and step
        2. Idempotency: block if step already SENT
        3. Eligibility: fail closed on any eligibility violation
        4. Draft verification: draft must exist and be APPROVED
        5. Fresh reply check: cancel and stop sequence if reply found
        6. SafetyController comprehensive authorization
        7. Gmail account connectivity verification
        8. Dispatch via GmailDispatchService (one message only)
        9. Record OutreachMessage + SendAttempt
        10. Update step and sequence state
        11. Audit trail

        Raises:
            FollowUpDispatchSequenceNotFoundError
            FollowUpDispatchStepNotFoundError
            FollowUpDispatchIdempotentError
            FollowUpDispatchEligibilityError
            FollowUpDispatchDraftNotFoundError
            FollowUpDispatchReplyDetectedError
            FollowUpDispatchSafetyError
            FollowUpDispatchGmailError
        """
        await self._log_audit(
            db=db,
            action="follow_up_dispatch_requested",
            owner_id=owner_id,
            run_status=AgentRunStatus.PENDING,
            input_data={"sequence_id": str(sequence_id), "step_id": str(step_id)},
        )

        # ── 1. Load sequence ──────────────────────────────────────────────────
        sequence = await db.scalar(
            select(FollowUpSequence).where(FollowUpSequence.id == sequence_id).with_for_update()
        )
        if not sequence:
            raise FollowUpDispatchSequenceNotFoundError(
                f"Follow-up sequence {sequence_id} does not exist."
            )

        # ── 2. Load step ──────────────────────────────────────────────────────
        step = await db.scalar(
            select(FollowUpStep).where(
                FollowUpStep.id == step_id,
                FollowUpStep.sequence_id == sequence_id,
            ).with_for_update()
        )
        if not step:
            raise FollowUpDispatchStepNotFoundError(
                f"Follow-up step {step_id} not found in sequence {sequence_id}."
            )

        # ── 3. Idempotency guard ──────────────────────────────────────────────
        if step.status == FollowUpStepStatus.SENT:
            raise FollowUpDispatchIdempotentError(
                f"Follow-up step {step_id} has already been sent (idempotency guard)."
            )
        if step.status in (
            FollowUpStepStatus.SKIPPED,
            FollowUpStepStatus.CANCELLED,
            FollowUpStepStatus.FAILED,
        ):
            raise FollowUpDispatchEligibilityError(
                f"Follow-up step {step_id} is in terminal status '{step.status.value}' and cannot be sent."
            )

        # ── 4. Eligibility check ──────────────────────────────────────────────
        eligibility = await self._eligibility_service.evaluate_sequence_eligibility(
            db=db, sequence=sequence, step=step
        )
        if not eligibility.eligible:
            err_msg = f"Follow-up eligibility check failed: {eligibility.reason}"
            await self._log_audit(
                db=db,
                action="follow_up_dispatch_blocked_eligibility",
                owner_id=owner_id,
                run_status=AgentRunStatus.FAILED,
                error_message=err_msg,
                input_data={"sequence_id": str(sequence_id), "step_id": str(step_id)},
            )
            raise FollowUpDispatchEligibilityError(err_msg)

        # ── 5. Verify draft is attached and APPROVED ──────────────────────────
        if not step.draft_id:
            raise FollowUpDispatchDraftNotFoundError(
                f"Follow-up step {step_id} has no draft attached. "
                "Generate and approve a draft before dispatching."
            )

        draft = await db.scalar(
            select(OutreachDraft).where(OutreachDraft.id == step.draft_id).with_for_update()
        )
        if not draft:
            raise FollowUpDispatchDraftNotFoundError(
                f"OutreachDraft {step.draft_id} attached to step {step_id} no longer exists."
            )

        if draft.status != OutreachDraftStatus.APPROVED:
            raise FollowUpDispatchEligibilityError(
                f"Draft status must be APPROVED before dispatch "
                f"(current status: {draft.status.value}). "
                "Approve the draft via Gate 2 before sending."
            )

        # Duplicate send guard: block if draft was already SENT
        if draft.status == OutreachDraftStatus.SENT:
            raise FollowUpDispatchIdempotentError(
                f"Draft {draft.id} has already been sent."
            )

        existing_sent_msg = await db.scalar(
            select(OutreachMessage).where(
                OutreachMessage.draft_id == draft.id,
                OutreachMessage.status == OutreachMessageStatus.SENT,
            )
        )
        if existing_sent_msg:
            raise FollowUpDispatchIdempotentError(
                f"An OutreachMessage already exists for draft {draft.id} (idempotency guard)."
            )

        # ── 6. Fresh database reply check ─────────────────────────────────────
        reply_detected = await self._fresh_reply_check(db=db, sequence=sequence, step=step)
        if reply_detected:
            # Terminate sequence to prevent sending into a replied thread
            now = datetime.now(timezone.utc)
            sequence.status = FollowUpSequenceStatus.STOPPED
            sequence.stop_reason = FollowUpStopReason.REPLIED
            sequence.stopped_at = now
            step.status = FollowUpStepStatus.CANCELLED
            err_msg = (
                f"Dispatch blocked: a prospect reply was detected on the thread "
                f"for sequence {sequence_id}. Sequence terminated."
            )
            await self._log_audit(
                db=db,
                action="follow_up_dispatch_blocked_reply",
                owner_id=owner_id,
                run_status=AgentRunStatus.FAILED,
                error_message=err_msg,
                input_data={"sequence_id": str(sequence_id), "step_id": str(step_id)},
            )
            await db.commit()
            raise FollowUpDispatchReplyDetectedError(err_msg)

        # ── 7. SafetyController comprehensive authorization ───────────────────
        safety_result = await self._safety_controller.authorize(
            db, draft_id=draft.id, record_blocked_attempt=True
        )
        if not safety_result.allowed:
            err_msg = f"Safety check blocked follow-up dispatch: {safety_result.blocked_reason}"
            await self._log_audit(
                db=db,
                action="follow_up_dispatch_blocked_safety",
                owner_id=owner_id,
                run_status=AgentRunStatus.FAILED,
                error_message=err_msg,
                input_data={
                    "sequence_id": str(sequence_id),
                    "step_id": str(step_id),
                    "draft_id": str(draft.id),
                    "violations": str(safety_result.violations),
                },
            )
            await db.commit()
            raise FollowUpDispatchSafetyError(err_msg)

        # ── 8. Verify owner Gmail account is CONNECTED ────────────────────────
        account: Optional[GmailAccount] = await db.scalar(
            select(GmailAccount).where(
                GmailAccount.owner_id == owner_id,
                GmailAccount.connection_status == GmailConnectionStatus.CONNECTED,
            )
        )
        if not account or not account.encrypted_refresh_token:
            err_msg = "No active connected Gmail account found for owner."
            now = datetime.now(timezone.utc)
            attempt = SendAttempt(
                draft_id=draft.id,
                lead_id=draft.lead_id,
                recipient_email=draft.recipient_email,
                attempted_at=now,
                result=SendAttemptResult.BLOCKED,
                failure_reason=err_msg,
            )
            db.add(attempt)
            await self._log_audit(
                db=db,
                action="follow_up_dispatch_blocked_gmail",
                owner_id=owner_id,
                run_status=AgentRunStatus.FAILED,
                error_message=err_msg,
                input_data={"sequence_id": str(sequence_id), "step_id": str(step_id)},
            )
            await db.commit()
            raise FollowUpDispatchGmailError(err_msg)

        # ── 9. Dispatch via Gmail API ─────────────────────────────────────────
        try:
            dispatch_result = await self._dispatch_service.dispatch_draft(
                account=account, draft=draft
            )
        except GmailDispatchError as exc:
            now = datetime.now(timezone.utc)
            attempt = SendAttempt(
                draft_id=draft.id,
                lead_id=draft.lead_id,
                recipient_email=draft.recipient_email,
                attempted_at=now,
                result=SendAttemptResult.FAILED,
                failure_reason=str(exc),
            )
            db.add(attempt)
            await self._log_audit(
                db=db,
                action="follow_up_dispatch_gmail_failed",
                owner_id=owner_id,
                run_status=AgentRunStatus.FAILED,
                error_message=str(exc),
                input_data={
                    "sequence_id": str(sequence_id),
                    "step_id": str(step_id),
                    "draft_id": str(draft.id),
                    "recipient_email": draft.recipient_email,
                },
            )
            await db.commit()
            raise FollowUpDispatchGmailError(
                f"Gmail API dispatch failed: {str(exc)}"
            ) from exc

        # ── 10. Record success artifacts ──────────────────────────────────────
        now = dispatch_result.sent_at

        # Mark draft as SENT
        draft.status = OutreachDraftStatus.SENT

        # Create OutreachMessage
        message = OutreachMessage(
            draft_id=draft.id,
            lead_id=draft.lead_id,
            recipient_email=draft.recipient_email,
            subject=draft.subject,
            gmail_message_id=dispatch_result.gmail_message_id,
            gmail_thread_id=dispatch_result.gmail_thread_id,
            sent_at=now,
            status=OutreachMessageStatus.SENT,
        )
        db.add(message)
        await db.flush()

        # Record SendAttempt
        attempt = SendAttempt(
            draft_id=draft.id,
            lead_id=draft.lead_id,
            recipient_email=draft.recipient_email,
            attempted_at=now,
            result=SendAttemptResult.SUCCESS,
            gmail_message_id=dispatch_result.gmail_message_id,
            gmail_thread_id=dispatch_result.gmail_thread_id,
        )
        db.add(attempt)
        await db.flush()

        # ── 11. Update step and sequence state ────────────────────────────────
        step.status = FollowUpStepStatus.SENT
        step.executed_at = now

        sequence_completed = await self._advance_or_complete_sequence(
            db=db,
            sequence=sequence,
            completed_step=step,
            now=now,
        )

        # ── 12. Audit success ─────────────────────────────────────────────────
        await self._log_audit(
            db=db,
            action="follow_up_dispatch_success",
            owner_id=owner_id,
            run_status=AgentRunStatus.COMPLETED,
            input_data={
                "sequence_id": str(sequence_id),
                "step_id": str(step_id),
                "step_number": step.step_number,
                "draft_id": str(draft.id),
                "recipient_email": draft.recipient_email,
                "gmail_message_id": dispatch_result.gmail_message_id,
                "gmail_thread_id": dispatch_result.gmail_thread_id,
                "sequence_completed": sequence_completed,
            },
        )

        log.info(
            "Follow-up step dispatched successfully",
            sequence_id=str(sequence_id),
            step_id=str(step_id),
            step_number=step.step_number,
            gmail_message_id=dispatch_result.gmail_message_id,
            sequence_completed=sequence_completed,
        )

        return FollowUpDispatchResult(
            outreach_message_id=message.id,
            send_attempt_id=attempt.id,
            gmail_message_id=dispatch_result.gmail_message_id,
            gmail_thread_id=dispatch_result.gmail_thread_id,
            sent_at=now,
            recipient_email=draft.recipient_email,
            subject=draft.subject,
            sequence_id=sequence_id,
            step_id=step_id,
            step_number=step.step_number,
            sequence_completed=sequence_completed,
        )
