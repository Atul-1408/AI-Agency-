"""
Deterministic Follow-up Eligibility Service.

Evaluates whether a FollowUpSequence and its current FollowUpStep are eligible to proceed.
Adheres strictly to the pre-send safety architecture:
- Reuses SafetyController's suppression, circuit breaker, and health checks as the single source of truth.
- Fails closed on any ambiguity or safety breach.
- NEVER sends emails.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from models import Lead, LeadStatus
from models.follow_up import (
    FollowUpSequence,
    FollowUpSequenceStatus,
    FollowUpStep,
    FollowUpStepStatus,
    FollowUpStopReason,
)
from models.outreach import (
    CircuitBreakerState,
    GmailAccount,
    GmailConnectionStatus,
    OutreachMessage,
    OutreachMessageStatus,
)
from services.safety_controller import SafetyController

log = structlog.get_logger(__name__)


@dataclass
class FollowUpEligibilityResult:
    """Deterministic result of follow-up sequence and step eligibility check."""
    eligible: bool
    reason: Optional[str] = None
    checks_passed: Dict[str, bool] = field(default_factory=dict)
    sequence_status: Optional[FollowUpSequenceStatus] = None
    step_status: Optional[FollowUpStepStatus] = None


class FollowUpEligibilityService:
    """
    Evaluates follow-up sequence and step readiness without taking autonomous sending actions.
    """

    def __init__(self, safety_controller: Optional[SafetyController] = None):
        self._safety_controller = safety_controller or SafetyController()

    async def evaluate_sequence_eligibility(
        self,
        db: AsyncSession,
        sequence: FollowUpSequence,
        step: Optional[FollowUpStep] = None,
    ) -> FollowUpEligibilityResult:
        """
        Verify all conditions for follow-up sequence progression:
        1. Sequence status == ACTIVE
        2. Not stopped (no reply detected, not owner stopped)
        3. Original outreach message exists and status == SENT
        4. Lead exists and is not REJECTED or DISQUALIFIED
        5. Step is PENDING or READY
        6. Recipient is not suppressed
        7. Owner's Gmail account is CONNECTED and healthy
        8. Circuit breaker permits operations
        """
        checks: Dict[str, bool] = {}

        # 1. Sequence Status Check
        if sequence.status != FollowUpSequenceStatus.ACTIVE:
            checks["sequence_active"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason=f"Sequence is not active (current status: {sequence.status.value}, stop_reason: {sequence.stop_reason}).",
                checks_passed=checks,
                sequence_status=sequence.status,
            )
        checks["sequence_active"] = True

        # 2. Check if a stop reason was recorded
        if sequence.stop_reason is not None:
            checks["no_stop_reason"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason=f"Sequence has stop reason set: {sequence.stop_reason.value}",
                checks_passed=checks,
                sequence_status=sequence.status,
            )
        checks["no_stop_reason"] = True

        # 3. Original Message Verification
        if not sequence.original_message_id:
            checks["original_message_exists"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason="Sequence has no associated original outreach message.",
                checks_passed=checks,
                sequence_status=sequence.status,
            )

        orig_msg = await db.scalar(
            select(OutreachMessage).where(OutreachMessage.id == sequence.original_message_id)
        )
        if not orig_msg:
            checks["original_message_exists"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason=f"Original outreach message {sequence.original_message_id} not found in database.",
                checks_passed=checks,
                sequence_status=sequence.status,
            )
        checks["original_message_exists"] = True

        if orig_msg.status != OutreachMessageStatus.SENT:
            checks["original_message_sent"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason=f"Original outreach message status is '{orig_msg.status.value}', expected 'sent'.",
                checks_passed=checks,
                sequence_status=sequence.status,
            )
        checks["original_message_sent"] = True

        # 4. Lead Status Check
        lead = await db.scalar(select(Lead).where(Lead.id == sequence.lead_id))
        if not lead:
            checks["lead_exists"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason=f"Lead {sequence.lead_id} not found.",
                checks_passed=checks,
                sequence_status=sequence.status,
            )
        checks["lead_exists"] = True

        if lead.status in (LeadStatus.REJECTED, LeadStatus.DISQUALIFIED):
            checks["lead_not_disqualified"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason=f"Associated lead is disqualified or rejected (status: {lead.status.value}).",
                checks_passed=checks,
                sequence_status=sequence.status,
            )
        checks["lead_not_disqualified"] = True

        # 5. Step Status Check (if step provided)
        if step is not None:
            if step.status not in (FollowUpStepStatus.PENDING, FollowUpStepStatus.READY):
                checks["step_pending_or_ready"] = False
                return FollowUpEligibilityResult(
                    eligible=False,
                    reason=f"Follow-up step {step.step_number} status is '{step.status.value}', expected pending or ready.",
                    checks_passed=checks,
                    sequence_status=sequence.status,
                    step_status=step.status,
                )
            checks["step_pending_or_ready"] = True

        # 6. Suppression Check via SafetyController
        recipient_email = orig_msg.recipient_email
        suppression = await self._safety_controller.check_suppression(
            db, email=recipient_email, domain=lead.domain
        )
        if suppression is not None:
            checks["not_suppressed"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason=f"Recipient email '{recipient_email}' or domain '{lead.domain}' is on suppression list (reason: {suppression.reason.value}).",
                checks_passed=checks,
                sequence_status=sequence.status,
            )
        checks["not_suppressed"] = True

        # 7. Gmail Connectivity & Health
        gmail_ok, gmail_err = await self._safety_controller.check_gmail_health(db)
        if not gmail_ok:
            checks["gmail_healthy"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason=f"Gmail health check failure: {gmail_err}",
                checks_passed=checks,
                sequence_status=sequence.status,
            )
        checks["gmail_healthy"] = True

        # 8. Circuit Breaker Check
        cb_state = await self._safety_controller.circuit_breaker.evaluate_dynamic_state(db)
        cb_permits, cb_reason = self._safety_controller.circuit_breaker.permits_send(cb_state)
        if not cb_permits:
            checks["circuit_breaker_permits"] = False
            return FollowUpEligibilityResult(
                eligible=False,
                reason=f"Circuit breaker violation: {cb_reason} (state: {cb_state.value}).",
                checks_passed=checks,
                sequence_status=sequence.status,
            )
        checks["circuit_breaker_permits"] = True

        # All checks passed
        return FollowUpEligibilityResult(
            eligible=True,
            reason=None,
            checks_passed=checks,
            sequence_status=sequence.status,
            step_status=step.status if step else None,
        )
