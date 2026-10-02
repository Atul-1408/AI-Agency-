"""
Follow-up Draft Generation Service.

Orchestrates Stage 4.6 Follow-up Draft Generation and Gate 2 Human Approval readiness:
- Evaluates strict eligibility using FollowUpEligibilityService
- Performs a fresh reply-state check before generation to prevent race conditions
- Personalizes follow-up drafts using only trusted Phase 2 audit findings
- Strictly neutralizes prompt injection attempts
- Persists OutreachDraft with status = PENDING_APPROVAL
- Associates draft with lead_id, follow_up_sequence_id, and follow_up_step_id
- Enforces database-level uniqueness to prevent duplicate active drafts per step
- Strictly SEND-FREE: never calls Gmail messages.send or consumes send quota
- Logs immutable audit events in agent_runs
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import html
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from models import (
    AgentRun,
    AgentRunStatus,
    Lead,
    LeadResearch,
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
    OutreachDraft,
    OutreachDraftStatus,
    OutreachMessage,
    OutreachMessageStatus,
)
from services.follow_up_eligibility_service import (
    FollowUpEligibilityResult,
    FollowUpEligibilityService,
)
from services.personalization_engine import (
    extract_factual_observations,
    sanitize_text,
)

from services.follow_up_service import SequenceNotFoundError

log = structlog.get_logger(__name__)


# ── Domain Exceptions ─────────────────────────────────────────────────────────

class FollowUpDraftError(Exception):
    """Base exception for follow-up draft generation errors."""
    pass


class StepNotFoundError(FollowUpDraftError):
    """Raised when sequence step is not found."""
    pass


class FollowUpDraftEligibilityError(FollowUpDraftError):
    """Raised when a sequence or step fails pre-draft eligibility checks."""
    pass


class ReplyDetectedError(FollowUpDraftError):
    """Raised when a verified prospect reply is detected prior to drafting."""
    pass


# ── Anti-Hallucination & Prohibited Phrases ───────────────────────────────────

PROHIBITED_PHRASES = [
    re.compile(r"i\s+spoke\s+with\s+you", re.IGNORECASE),
    re.compile(r"you\s+asked\s+me", re.IGNORECASE),
    re.compile(r"as\s+discussed", re.IGNORECASE),
    re.compile(r"following\s+up\s+on\s+our\s+call", re.IGNORECASE),
    re.compile(r"per\s+our\s+conversation", re.IGNORECASE),
    re.compile(r"our\s+phone\s+call", re.IGNORECASE),
]


def format_follow_up_subject(original_subject: Optional[str]) -> str:
    """
    Format follow-up subject cleanly:
    - Normalizes and removes multiple 'Re:' prefixes (e.g. 'Re: Re: Re:' -> 'Re:')
    - Ensures single 'Re: ' prefix
    - Strips control characters
    - Enforces 500-char max length
    """
    if not original_subject or not original_subject.strip():
        return "Following up regarding digital presence"

    cleaned = original_subject.strip()
    # Strip any leading 'Re:' prefixes recursively
    cleaned = re.sub(r"^(?:re:\s*)+", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = sanitize_text(cleaned, max_length=490)
    subject = f"Re: {cleaned}"
    return subject[:500]


def generate_follow_up_content(
    lead: Lead,
    research: Optional[LeadResearch],
    original_message: OutreachMessage,
    step_number: int,
) -> Tuple[str, str]:
    """
    Generate factual, plain-text follow-up draft content.
    Returns (subject, body_text).
    """
    company_name = sanitize_text(lead.company_name, max_length=80) or "your team"
    domain = sanitize_text(lead.domain, max_length=80) or "your website"

    # Subject line
    subject = format_follow_up_subject(original_message.subject)

    # Extract strictly factual findings from Phase 2 research
    observations: List[Dict[str, str]] = []
    if research:
        observations = extract_factual_observations(research)

    primary_finding = observations[0]["detail"] if observations else "modern mobile formatting and asset loading speeds"
    secondary_finding = observations[1]["detail"] if len(observations) > 1 else None

    # Step-specific tailored plain text
    if step_number == 1:
        body_text = (
            f"Hi {company_name} team,\n\n"
            f"I wanted to quickly follow up on my earlier note regarding {domain}.\n\n"
            f"Specifically, our initial audit noted: {primary_finding}.\n\n"
            f"We have prepared a complimentary 3-page interactive redesign prototype showing how "
            f"resolving this can deliver a cleaner user experience and faster mobile conversions.\n\n"
            f"Would you be open to taking a look at the preview link this week?\n\n"
            f"Best regards,\n"
            f"Atul | AI Web Agency\n\n"
            f"---\n"
            f"If you prefer not to receive updates regarding {domain}, simply reply with 'unsubscribe' to be permanently excluded."
        )
    elif step_number == 2:
        finding_note = f"Along with {primary_finding}"
        if secondary_finding:
            finding_note += f", we also observed that {secondary_finding}"
        else:
            finding_note += ", modernizing asset delivery can significantly decrease bounce rates"

        body_text = (
            f"Hi {company_name} team,\n\n"
            f"Following up briefly on our prototype for {domain}.\n\n"
            f"{finding_note}.\n\n"
            f"Our team put together a live interactive concept that addresses these items directly. "
            f"Happy to send over the link if this is a priority for your team right now.\n\n"
            f"Would Thursday or Friday suit you for a 5-minute review?\n\n"
            f"Best regards,\n"
            f"Atul | AI Web Agency\n\n"
            f"---\n"
            f"If you prefer not to receive updates regarding {domain}, simply reply with 'unsubscribe' to be permanently excluded."
        )
    else:
        body_text = (
            f"Hi {company_name} team,\n\n"
            f"I wanted to check in one last time regarding {domain}.\n\n"
            f"If modernizing your site's performance and conversion layout is not on the agenda right now, "
            f"no worries at all—I will not follow up further.\n\n"
            f"If you ever wish to see the prototype concept in the future, please feel free to reach out anytime.\n\n"
            f"Wishing you and the {company_name} team all the best,\n"
            f"Atul | AI Web Agency\n\n"
            f"---\n"
            f"If you prefer not to receive updates regarding {domain}, simply reply with 'unsubscribe' to be permanently excluded."
        )

    # Anti-hallucination check: ensure no prohibited phrases were generated
    for pattern in PROHIBITED_PHRASES:
        if pattern.search(body_text):
            log.warning("Prohibited conversation claim pattern detected in follow-up generator", pattern=pattern.pattern)
            body_text = pattern.sub("our previous message", body_text)

    return subject, body_text


# ── Follow-Up Draft Service ───────────────────────────────────────────────────

class FollowUpDraftService:
    """
    Core service for evaluating, personalizing, and creating follow-up OutreachDraft records.
    """

    def __init__(self, eligibility_service: Optional[FollowUpEligibilityService] = None):
        self._eligibility_service = eligibility_service or FollowUpEligibilityService()

    async def generate_draft_for_step(
        self,
        db: AsyncSession,
        sequence_id: uuid.UUID,
        step_id: uuid.UUID,
        owner_id: str = "system",
    ) -> Tuple[OutreachDraft, bool]:
        """
        Generate and persist a follow-up draft for an eligible sequence step.
        Returns: (draft, is_existing)
        
        Guarantees:
        1. Evaluates eligibility via FollowUpEligibilityService.
        2. Performs fresh reply check to prevent race conditions.
        3. Enforces single active draft per step (idempotent, concurrency-safe).
        4. Draft status is strictly PENDING_APPROVAL (Gate 2 Human-in-the-Loop).
        5. Logs full audit trail in agent_runs.
        6. Strictly NO email sending.
        """
        now = datetime.now(timezone.utc)

        # Audit: draft generation requested
        audit_req = AgentRun(
            agent_name="follow_up",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "action": "followup_draft_generation_requested",
                "sequence_id": str(sequence_id),
                "step_id": str(step_id),
                "owner": owner_id,
            },
            started_at=now,
            completed_at=now,
        )
        db.add(audit_req)
        await db.flush()

        # 1. Fetch Sequence and Step
        seq_stmt = (
            select(FollowUpSequence)
            .options(selectinload(FollowUpSequence.lead))
            .where(FollowUpSequence.id == sequence_id)
        )
        sequence = await db.scalar(seq_stmt)
        if not sequence:
            raise SequenceNotFoundError(f"Follow-up sequence {sequence_id} not found.")

        step = await db.scalar(
            select(FollowUpStep).where(
                FollowUpStep.id == step_id,
                FollowUpStep.sequence_id == sequence.id,
            )
        )
        if not step:
            raise StepNotFoundError(f"Follow-up step {step_id} not found in sequence {sequence_id}.")

        # 2. Check if a draft already exists for this step (Idempotency check)
        existing_draft = None
        if step.draft_id:
            existing_draft = await db.scalar(
                select(OutreachDraft).where(OutreachDraft.id == step.draft_id)
            )
        if not existing_draft:
            existing_draft = await db.scalar(
                select(OutreachDraft).where(OutreachDraft.follow_up_step_id == step.id)
            )

        if existing_draft:
            log.info(
                "Follow-up draft already exists for step, returning existing draft",
                step_id=str(step.id),
                draft_id=str(existing_draft.id),
                status=existing_draft.status.value,
            )
            return existing_draft, True

        # 3. Sequence state checks
        if sequence.status != FollowUpSequenceStatus.ACTIVE:
            audit_blocked = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.FAILED,
                input_data={
                    "action": "followup_draft_generation_blocked",
                    "sequence_id": str(sequence.id),
                    "step_id": str(step.id),
                    "reason": f"Sequence is not active (status: {sequence.status.value}).",
                    "owner": owner_id,
                },
                started_at=now,
                completed_at=now,
            )
            db.add(audit_blocked)
            await db.commit()
            raise FollowUpDraftEligibilityError(
                f"Sequence is not active (current status: '{sequence.status.value}', expected 'active')."
            )

        # 4. Step state checks
        if step.status not in (FollowUpStepStatus.PENDING, FollowUpStepStatus.READY):
            audit_blocked = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.FAILED,
                input_data={
                    "action": "followup_draft_generation_blocked",
                    "sequence_id": str(sequence.id),
                    "step_id": str(step.id),
                    "reason": f"Step is not in pending or ready status (status: {step.status.value}).",
                    "owner": owner_id,
                },
                started_at=now,
                completed_at=now,
            )
            db.add(audit_blocked)
            await db.commit()
            raise FollowUpDraftEligibilityError(
                f"Cannot generate draft: step status is '{step.status.value}', expected 'pending' or 'ready'."
            )

        # 5. Fresh Reply-State Check (Race Condition Protection)
        # Check if an InboundMessage was detected for this sequence, lead, or thread
        orig_msg = None
        if sequence.original_message_id:
            orig_msg = await db.scalar(
                select(OutreachMessage).where(OutreachMessage.id == sequence.original_message_id)
            )

        inbound_reply = await db.scalar(
            select(InboundMessage).where(
                (InboundMessage.matched_sequence_id == sequence.id)
                | (
                    (InboundMessage.matched_outreach_message_id == sequence.original_message_id)
                    if sequence.original_message_id
                    else False
                )
                | (
                    (InboundMessage.gmail_thread_id == orig_msg.gmail_thread_id)
                    if orig_msg and orig_msg.gmail_thread_id
                    else False
                )
            )
        )

        if inbound_reply:
            log.warning(
                "Fresh reply check detected prospect reply before follow-up draft generation. Stopping sequence.",
                sequence_id=str(sequence.id),
                inbound_id=str(inbound_reply.id),
            )
            # Stop sequence immediately
            sequence.status = FollowUpSequenceStatus.STOPPED
            sequence.stop_reason = FollowUpStopReason.REPLIED
            sequence.stopped_at = now
            sequence.next_action_at = None
            step.status = FollowUpStepStatus.CANCELLED

            audit_blocked = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.FAILED,
                input_data={
                    "action": "followup_draft_generation_blocked",
                    "sequence_id": str(sequence.id),
                    "step_id": str(step.id),
                    "reason": "Verified prospect reply detected.",
                    "inbound_message_id": str(inbound_reply.id),
                    "owner": owner_id,
                },
                started_at=now,
                completed_at=now,
            )
            db.add(audit_blocked)

            audit_stopped = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.COMPLETED,
                input_data={
                    "action": "followup_sequence_stopped",
                    "sequence_id": str(sequence.id),
                    "lead_id": str(sequence.lead_id),
                    "stop_reason": FollowUpStopReason.REPLIED.value,
                    "cancelled_steps": 1,
                    "owner": owner_id,
                },
                started_at=now,
                completed_at=now,
            )
            db.add(audit_stopped)
            await db.commit()
            raise ReplyDetectedError("Verified prospect reply detected. Follow-up sequence has been stopped.")

        # 6. Evaluate complete eligibility using FollowUpEligibilityService
        eligibility = await self._eligibility_service.evaluate_sequence_eligibility(
            db=db, sequence=sequence, step=step
        )
        if not eligibility.eligible:
            audit_blocked = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.FAILED,
                input_data={
                    "action": "followup_draft_generation_blocked",
                    "sequence_id": str(sequence.id),
                    "step_id": str(step.id),
                    "reason": eligibility.reason,
                    "checks_passed": eligibility.checks_passed,
                    "owner": owner_id,
                },
                started_at=now,
                completed_at=now,
            )
            db.add(audit_blocked)
            await db.commit()
            raise FollowUpDraftEligibilityError(f"Step is not eligible for draft generation: {eligibility.reason}")

        if not orig_msg:
            raise FollowUpDraftEligibilityError("Original outreach message not found.")

        # 7. Load Lead Research for Factual Personalization
        lead = sequence.lead
        research = await db.scalar(
            select(LeadResearch).where(LeadResearch.lead_id == sequence.lead_id)
        )

        # 8. Generate Factual Content
        try:
            subject, body_text = generate_follow_up_content(
                lead=lead,
                research=research,
                original_message=orig_msg,
                step_number=step.step_number,
            )
        except Exception as exc:
            log.error("Failed to personalize follow-up draft", error=str(exc))
            audit_failed = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.FAILED,
                input_data={
                    "action": "followup_draft_generation_failed",
                    "sequence_id": str(sequence.id),
                    "step_id": str(step.id),
                    "error": str(exc),
                    "owner": owner_id,
                },
                started_at=now,
                completed_at=now,
            )
            db.add(audit_failed)
            await db.commit()
            raise FollowUpDraftError(f"Personalization error: {str(exc)}") from exc

        # 9. Create OutreachDraft strictly in PENDING_APPROVAL status
        draft = OutreachDraft(
            lead_id=sequence.lead_id,
            recipient_email=orig_msg.recipient_email,
            subject=subject,
            body_text=body_text,
            body_html=None,  # Plain text only
            status=OutreachDraftStatus.PENDING_APPROVAL,
            follow_up_sequence_id=sequence.id,
            follow_up_step_id=step.id,
        )
        db.add(draft)

        try:
            await db.flush()
            # Link draft back to step
            step.draft_id = draft.id
            await db.commit()
            await db.refresh(draft)
        except IntegrityError as exc:
            # Concurrency race: Another worker/request committed a draft for this step simultaneously
            log.warning(
                "Database constraint caught concurrent draft creation for step. Fetching existing draft.",
                step_id=str(step.id),
                error=str(exc),
            )
            await db.rollback()
            existing = await db.scalar(
                select(OutreachDraft).where(OutreachDraft.follow_up_step_id == step.id)
            )
            if existing:
                return existing, True
            raise

        # 10. Audit event: followup_draft_generated
        audit_success = AgentRun(
            agent_name="follow_up",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "action": "followup_draft_generated",
                "sequence_id": str(sequence.id),
                "step_id": str(step.id),
                "step_number": step.step_number,
                "draft_id": str(draft.id),
                "recipient_email": draft.recipient_email,
                "status": draft.status.value,
                "owner": owner_id,
            },
            output_data={
                "subject": draft.subject,
                "length_chars": len(draft.body_text),
            },
            started_at=now,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(audit_success)
        await db.commit()

        log.info(
            "Follow-up draft successfully generated and placed in PENDING_APPROVAL",
            draft_id=str(draft.id),
            sequence_id=str(sequence.id),
            step_id=str(step.id),
            status=draft.status.value,
        )
        return draft, False
