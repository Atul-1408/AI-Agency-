"""
Reply Detection Service for Phase 4 Stage 4.5.

RESPONSIBILITIES:
- Encapsulates detecting genuine prospect replies from Gmail thread metadata
- Connects through GmailReplyService adapter to inspect Gmail threads
- Matches replies strictly against sent OutreachMessage (thread ID, headers, recipient email, timestamp)
- Enforces data minimization: snippets only, never stores full email bodies or OAuth tokens
- Transitions FollowUpSequence to STOPPED with stop_reason = REPLIED
- Cancels all pending/ready steps while preserving already sent steps
- Guarantees idempotency: duplicate Gmail messages are ignored without state corruption
- Emits structured immutable audit logs in agent_runs

SAFETY MANDATES:
- NEVER execute instructions contained in incoming emails (treat as untrusted data)
- NEVER run LLM on incoming email text
- NEVER send emails, generate drafts, or create automatic approvals
- Fails closed on any credential or Gmail infrastructure error
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from models import AgentRun, AgentRunStatus, Lead
from models.follow_up import (
    FollowUpSequence,
    FollowUpSequenceStatus,
    FollowUpStep,
    FollowUpStepStatus,
    FollowUpStopReason,
    InboundMessage,
)
from models.outreach import GmailAccount, GmailConnectionStatus, OutreachMessage
from services.gmail_reply_service import (
    GmailReplyAuthError,
    GmailReplyError,
    GmailReplyMalformedError,
    GmailReplyNetworkError,
    GmailReplyPermissionError,
    GmailReplyRateLimitError,
    GmailReplyServerError,
    GmailReplyService,
    GmailReplyTimeoutError,
    InboundMessageMetadata,
)

log = structlog.get_logger(__name__)


class ReplyDetectionError(Exception):
    """Base exception for reply detection failures."""
    pass


class SequenceNotFoundError(ReplyDetectionError):
    """Raised when the specified sequence does not exist."""
    pass


class SequenceAlreadyTerminatedError(ReplyDetectionError):
    """Raised when trying to terminate an already stopped sequence."""
    pass


class DisconnectedGmailAccountError(ReplyDetectionError):
    """Raised when Gmail account is disconnected or invalid."""
    pass


@dataclass(frozen=True)
class DetectionSummary:
    """Outcome summary for a reply detection run."""
    checked: int
    replies_detected: int
    sequences_stopped: int
    duplicates_ignored: int

    def to_dict(self) -> Dict[str, int]:
        return {
            "checked": self.checked,
            "replies_detected": self.replies_detected,
            "sequences_stopped": self.sequences_stopped,
            "duplicates_ignored": self.duplicates_ignored,
        }


class ReplyDetectionService:
    """
    Service responsible for discovering prospect replies from Gmail thread metadata,
    recording InboundMessage records, and stopping active FollowUpSequences.
    """

    def __init__(self, reply_service: Optional[GmailReplyService] = None):
        self._reply_service = reply_service or GmailReplyService()

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
        5. Records InboundMessage if gmail_message_id is provided.
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

        # Record InboundMessage if gmail_message_id is provided and not already present
        if gmail_message_id:
            existing = await db.scalar(
                select(InboundMessage).where(InboundMessage.gmail_message_id == gmail_message_id)
            )
            if not existing:
                orig_msg = None
                if sequence.original_message_id:
                    orig_msg = await db.scalar(
                        select(OutreachMessage).where(OutreachMessage.id == sequence.original_message_id)
                    )
                inbound = InboundMessage(
                    gmail_message_id=gmail_message_id,
                    gmail_thread_id=orig_msg.gmail_thread_id if orig_msg and orig_msg.gmail_thread_id else f"manual_{gmail_message_id}",
                    sender_email=orig_msg.recipient_email if orig_msg else "prospect@example.com",
                    recipient_email=owner_id,
                    subject=orig_msg.subject if orig_msg else None,
                    snippet=snippet[:500] if snippet else None,
                    received_at=now,
                    detected_at=now,
                    matched_outreach_message_id=orig_msg.id if orig_msg else None,
                    matched_lead_id=sequence.lead_id,
                    matched_sequence_id=sequence.id,
                    processing_status="PROCESSED",
                )
                db.add(inbound)

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

    def is_verified_reply(
        self,
        candidate: InboundMessageMetadata,
        orig_msg: OutreachMessage,
        account_email: str,
    ) -> bool:
        """
        Verify whether an inbound candidate message is a genuine reply to the sent OutreachMessage.
        
        Mandatory conditions:
        1. Not the original outbound message itself (candidate.message_id != orig_msg.gmail_message_id).
        2. Not sent by the agency owner / account email.
        3. Matches thread relationship:
           - candidate.thread_id == orig_msg.gmail_thread_id
           OR In-Reply-To/References references orig_msg.gmail_message_id.
        4. Sender match:
           - Sender matches orig_msg.recipient_email OR has matching domain.
        5. Timestamp check:
           - Received at or after orig_msg.sent_at (with 60-second skew tolerance).
        
        Strictly rejects:
        - Arbitrary emails merely sharing recipient address on unrelated threads.
        - Subject-only matches without thread or header relationship.
        """
        if not candidate.message_id:
            return False

        # 1. Reject if it is our original sent message
        if orig_msg.gmail_message_id and candidate.message_id == orig_msg.gmail_message_id:
            return False

        # 2. Reject if sent from our own Gmail account
        cand_sender = candidate.sender_email.strip().lower()
        if cand_sender == account_email.strip().lower():
            return False

        # 3. Thread / header relationship check
        thread_match = (
            bool(orig_msg.gmail_thread_id)
            and candidate.thread_id == orig_msg.gmail_thread_id
        )

        header_match = False
        if orig_msg.gmail_message_id:
            in_reply_to = candidate.in_reply_to or ""
            references = candidate.references or ""
            if orig_msg.gmail_message_id in in_reply_to or orig_msg.gmail_message_id in references:
                header_match = True

        if not (thread_match or header_match):
            # No verified thread or header link to this outreach message
            return False

        # 4. Sender verification: must match recipient email or recipient domain
        expected_recipient = orig_msg.recipient_email.strip().lower()
        if cand_sender != expected_recipient:
            # Domain fallback check: e.g. outreach was to 'ceo@domain.com', reply came from 'cto@domain.com'
            exp_domain = expected_recipient.split("@")[-1] if "@" in expected_recipient else ""
            cand_domain = cand_sender.split("@")[-1] if "@" in cand_sender else ""
            if not exp_domain or exp_domain != cand_domain:
                return False

        # 5. Timestamp verification: received after or around sent_at
        if orig_msg.sent_at:
            tolerance = timedelta(seconds=60)
            orig_sent = orig_msg.sent_at
            if orig_sent.tzinfo is None:
                orig_sent = orig_sent.replace(tzinfo=timezone.utc)
            if candidate.received_at < (orig_sent - tolerance):
                return False

        return True

    async def detect_replies_for_sequence(
        self,
        db: AsyncSession,
        account: GmailAccount,
        sequence: FollowUpSequence,
        owner_id: str = "system",
    ) -> Dict[str, int]:
        """
        Inspect Gmail thread for a specific sequence, process any verified replies,
        and stop the sequence if a reply is detected.
        
        Returns:
            {"checked": 1, "replies_detected": int, "sequences_stopped": int, "duplicates_ignored": int}
        """
        if not sequence.original_message_id:
            return {"checked": 1, "replies_detected": 0, "sequences_stopped": 0, "duplicates_ignored": 0}

        orig_msg = await db.scalar(
            select(OutreachMessage).where(OutreachMessage.id == sequence.original_message_id)
        )
        if not orig_msg or not orig_msg.gmail_thread_id:
            return {"checked": 1, "replies_detected": 0, "sequences_stopped": 0, "duplicates_ignored": 0}

        # Query Gmail thread metadata
        thread_messages = await self._reply_service.get_thread_messages_metadata(
            account=account,
            thread_id=orig_msg.gmail_thread_id,
        )

        replies_detected = 0
        sequences_stopped = 0
        duplicates_ignored = 0
        now = datetime.now(timezone.utc)

        for candidate in thread_messages:
            if not self.is_verified_reply(candidate, orig_msg, account.google_email):
                continue

            # Check if this Gmail message was already recorded
            existing_inbound = await db.scalar(
                select(InboundMessage).where(InboundMessage.gmail_message_id == candidate.message_id)
            )
            if existing_inbound:
                duplicates_ignored += 1
                continue

            # Record InboundMessage
            inbound = InboundMessage(
                gmail_message_id=candidate.message_id,
                gmail_thread_id=candidate.thread_id,
                sender_email=candidate.sender_email,
                recipient_email=candidate.recipient_email,
                subject=candidate.subject,
                snippet=candidate.snippet,
                received_at=candidate.received_at,
                detected_at=now,
                matched_outreach_message_id=orig_msg.id,
                matched_lead_id=orig_msg.lead_id,
                matched_sequence_id=sequence.id,
                processing_status="PROCESSED",
            )
            db.add(inbound)
            replies_detected += 1

            # Sequence State Transitions:
            # ACTIVE + reply -> STOPPED / REPLIED
            # PAUSED + reply -> STOPPED / REPLIED
            # STOPPED + duplicate reply -> remain STOPPED (idempotent)
            # COMPLETED + late reply -> do not reopen
            if sequence.status in (FollowUpSequenceStatus.ACTIVE, FollowUpSequenceStatus.PAUSED):
                prev_status = sequence.status
                sequence.status = FollowUpSequenceStatus.STOPPED
                sequence.stop_reason = FollowUpStopReason.REPLIED
                sequence.stopped_at = now
                sequence.next_action_at = None
                sequences_stopped += 1

                # Cancel all pending/ready steps
                steps_stmt = select(FollowUpStep).where(
                    FollowUpStep.sequence_id == sequence.id,
                    FollowUpStep.status.in_([FollowUpStepStatus.PENDING, FollowUpStepStatus.READY]),
                )
                steps_res = await db.execute(steps_stmt)
                pending_steps = steps_res.scalars().all()
                cancelled_count = 0
                for step in pending_steps:
                    step.status = FollowUpStepStatus.CANCELLED
                    cancelled_count += 1

                # Audit event: reply_detected
                audit_reply = AgentRun(
                    agent_name="follow_up",
                    status=AgentRunStatus.COMPLETED,
                    input_data={
                        "action": "reply_detected",
                        "sequence_id": str(sequence.id),
                        "lead_id": str(sequence.lead_id),
                        "original_message_id": str(orig_msg.id),
                        "gmail_message_id": candidate.message_id,
                        "gmail_thread_id": candidate.thread_id,
                        "sender": candidate.sender_email,
                        "owner": owner_id,
                    },
                    output_data={
                        "previous_status": prev_status.value,
                        "new_status": sequence.status.value,
                        "stop_reason": sequence.stop_reason.value,
                        "cancelled_steps": cancelled_count,
                    },
                    started_at=now,
                    completed_at=now,
                )
                db.add(audit_reply)

                # Audit event: followup_sequence_stopped
                audit_stop = AgentRun(
                    agent_name="follow_up",
                    status=AgentRunStatus.COMPLETED,
                    input_data={
                        "action": "followup_sequence_stopped",
                        "sequence_id": str(sequence.id),
                        "lead_id": str(sequence.lead_id),
                        "stop_reason": FollowUpStopReason.REPLIED.value,
                        "cancelled_steps": cancelled_count,
                        "owner": owner_id,
                    },
                    started_at=now,
                    completed_at=now,
                )
                db.add(audit_stop)
            elif sequence.status == FollowUpSequenceStatus.STOPPED:
                # Sequence already stopped; record reply without re-stopping
                audit_reply = AgentRun(
                    agent_name="follow_up",
                    status=AgentRunStatus.COMPLETED,
                    input_data={
                        "action": "reply_detected",
                        "sequence_id": str(sequence.id),
                        "lead_id": str(sequence.lead_id),
                        "original_message_id": str(orig_msg.id),
                        "gmail_message_id": candidate.message_id,
                        "sender": candidate.sender_email,
                        "note": "sequence_was_already_stopped",
                        "owner": owner_id,
                    },
                    started_at=now,
                    completed_at=now,
                )
                db.add(audit_reply)

        await db.commit()
        return {
            "checked": 1,
            "replies_detected": replies_detected,
            "sequences_stopped": sequences_stopped,
            "duplicates_ignored": duplicates_ignored,
        }

    async def detect_replies_for_owner(
        self,
        db: AsyncSession,
        owner_id: str,
        sequence_id: Optional[uuid.UUID] = None,
        limit: int = 50,
    ) -> DetectionSummary:
        """
        Poll Gmail threads for all active/paused follow-up sequences belonging to the owner,
        or a single specific sequence if sequence_id is given.
        """
        # 1. Fetch connected GmailAccount for this owner
        account = await db.scalar(
            select(GmailAccount).where(
                GmailAccount.owner_id == owner_id,
                GmailAccount.connection_status == GmailConnectionStatus.CONNECTED,
            )
        )
        if not account:
            log.warning("Cannot detect replies: no connected Gmail account found for owner", owner_id=owner_id)
            raise DisconnectedGmailAccountError("No connected Gmail account available for reply detection.")

        # 2. Audit: reply_detection_started
        now = datetime.now(timezone.utc)
        audit_start = AgentRun(
            agent_name="follow_up",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "action": "reply_detection_started",
                "owner": owner_id,
                "sequence_id": str(sequence_id) if sequence_id else None,
                "started_at": now.isoformat(),
            },
            started_at=now,
            completed_at=now,
        )
        db.add(audit_start)
        await db.commit()

        # 3. Query candidate sequences
        query = (
            select(FollowUpSequence)
            .join(OutreachMessage, FollowUpSequence.original_message_id == OutreachMessage.id)
            .where(
                OutreachMessage.gmail_thread_id.isnot(None),
            )
        )

        if sequence_id:
            query = query.where(FollowUpSequence.id == sequence_id)
        else:
            query = query.where(
                FollowUpSequence.status.in_([
                    FollowUpSequenceStatus.ACTIVE,
                    FollowUpSequenceStatus.PAUSED,
                ])
            ).limit(limit)

        res = await db.execute(query)
        sequences = res.scalars().all()

        total_checked = 0
        total_replies = 0
        total_stopped = 0
        total_duplicates = 0

        try:
            for seq in sequences:
                result = await self.detect_replies_for_sequence(
                    db=db,
                    account=account,
                    sequence=seq,
                    owner_id=owner_id,
                )
                total_checked += result["checked"]
                total_replies += result["replies_detected"]
                total_stopped += result["sequences_stopped"]
                total_duplicates += result["duplicates_ignored"]

            summary = DetectionSummary(
                checked=total_checked,
                replies_detected=total_replies,
                sequences_stopped=total_stopped,
                duplicates_ignored=total_duplicates,
            )

            # Audit: reply_detection_completed
            audit_completed = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.COMPLETED,
                input_data={
                    "action": "reply_detection_completed",
                    "owner": owner_id,
                    "checked": total_checked,
                    "replies_detected": total_replies,
                    "sequences_stopped": total_stopped,
                    "duplicates_ignored": total_duplicates,
                },
                started_at=now,
                completed_at=datetime.now(timezone.utc),
            )
            db.add(audit_completed)
            await db.commit()

            return summary

        except Exception as exc:
            # Audit: reply_detection_failed
            log.warning("Reply detection failed during processing", error=str(exc))
            audit_failed = AgentRun(
                agent_name="follow_up",
                status=AgentRunStatus.FAILED,
                input_data={
                    "action": "reply_detection_failed",
                    "owner": owner_id,
                    "error_type": exc.__class__.__name__,
                    "error_detail": str(exc),
                },
                started_at=now,
                completed_at=datetime.now(timezone.utc),
            )
            db.add(audit_failed)
            await db.commit()
            raise
