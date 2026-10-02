"""
Outreach Service — Phase 3 Stage 3.4.

Implements the Gate 2 Owner Approval workflow:
- Listing and filtering generated outreach drafts
- Draft detail retrieval with lead research evidence
- Owner approval (enforcing Gate 1 lead approval and MX verification)
- Owner rejection (with mandatory reason)
- Draft content editing strictly restricted to PENDING_APPROVAL
- Reset to PENDING_APPROVAL (for re-evaluating or editing approved/rejected drafts)
- Comprehensive audit tracking in the agent_runs table for all transitions and attempts
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models import (
    AgentRun,
    AgentRunStatus,
    EmailVerificationStatus,
    Lead,
    LeadResearch,
    LeadStatus,
)
from models.outreach import OutreachDraft, OutreachDraftStatus
from schemas.outreach import OutreachDraftResponse

log = structlog.get_logger(__name__)


class DraftNotFoundError(Exception):
    """Raised when an outreach draft is not found."""
    pass


class InvalidStateTransitionError(Exception):
    """Raised when an outreach draft transition violates safety or workflow rules."""
    pass


class OutreachService:
    """Service handling Gate 2 human approval lifecycle for cold outreach drafts."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _record_audit_event(
        self,
        action: str,
        draft_id: Optional[uuid.UUID],
        owner_email: str,
        status: AgentRunStatus,
        input_data: Optional[Dict[str, Any]] = None,
        output_data: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> AgentRun:
        """
        Record every approval, rejection, edit, or invalid transition attempt
        in the immutable agent_runs table for end-to-end auditability.
        """
        now = datetime.now(timezone.utc)
        run = AgentRun(
            agent_name="outreach_gate2",
            status=status,
            input_data={
                "action": action,
                "draft_id": str(draft_id) if draft_id else None,
                "owner": owner_email,
                **(input_data or {}),
            },
            output_data=output_data or {},
            error_message=error_message,
            started_at=now,
            completed_at=now,
        )
        self.db.add(run)
        await self.db.flush()
        return run

    @staticmethod
    def enrich_draft_response(draft: OutreachDraft) -> OutreachDraftResponse:
        """Convert OutreachDraft model to enriched schema with company and evidence details."""
        company_name = None
        lead_domain = None
        evidence = None

        if draft.lead:
            company_name = draft.lead.company_name
            lead_domain = draft.lead.domain
            if draft.lead.research and draft.lead.research.audit_findings:
                evidence = draft.lead.research.audit_findings

        return OutreachDraftResponse(
            id=draft.id,
            lead_id=draft.lead_id,
            company_name=company_name,
            lead_domain=lead_domain,
            recipient_email=draft.recipient_email,
            subject=draft.subject,
            body_text=draft.body_text,
            body_html=draft.body_html,
            evidence=evidence,
            status=draft.status,
            approved_at=draft.approved_at,
            approved_by=draft.approved_by,
            rejected_at=draft.rejected_at,
            rejected_by=draft.rejected_by,
            rejection_reason=draft.rejection_reason,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )

    async def list_drafts(
        self,
        status: Optional[OutreachDraftStatus] = None,
        lead_id: Optional[uuid.UUID] = None,
        recipient_email: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_before: Optional[datetime] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Tuple[int, List[OutreachDraftResponse]]:
        """
        List outreach drafts with filters and pagination.
        """
        query = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
        )

        if status is not None:
            query = query.where(OutreachDraft.status == status)

        if lead_id is not None:
            query = query.where(OutreachDraft.lead_id == lead_id)

        if recipient_email is not None and recipient_email.strip():
            query = query.where(
                func.lower(OutreachDraft.recipient_email) == recipient_email.lower().strip()
            )

        if created_after is not None:
            query = query.where(OutreachDraft.created_at >= created_after)

        if created_before is not None:
            query = query.where(OutreachDraft.created_at <= created_before)

        # Count total
        count_stmt = select(func.count()).select_from(query.order_by(None).subquery())
        total = (await self.db.execute(count_stmt)).scalar_one()

        # Apply ordering and pagination
        paginated_stmt = (
            query.order_by(OutreachDraft.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.db.execute(paginated_stmt)
        drafts = result.scalars().all()

        enriched = [self.enrich_draft_response(d) for d in drafts]
        return total, enriched

    async def get_draft_detail(self, draft_id: uuid.UUID) -> OutreachDraftResponse:
        """
        Retrieve detail for a single draft including evidence and approval/rejection metadata.
        """
        stmt = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
            .where(OutreachDraft.id == draft_id)
        )
        res = await self.db.execute(stmt)
        draft = res.scalar_one_or_none()
        if not draft:
            raise DraftNotFoundError(f"Outreach draft {draft_id} not found")

        return self.enrich_draft_response(draft)

    async def approve_draft(
        self,
        draft_id: uuid.UUID,
        owner_email: str,
    ) -> OutreachDraftResponse:
        """
        Owner approves a draft (Gate 2).
        Enforces:
        - Draft exists
        - Draft status is PENDING_APPROVAL
        - Associated lead is LeadStatus.APPROVED (Gate 1)
        - Recipient email is EmailVerificationStatus.MX_VERIFIED
        - Records approved_at, approved_by, transitions to APPROVED
        - Emits an immutable audit record in agent_runs
        """
        stmt = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
            .where(OutreachDraft.id == draft_id)
        )
        res = await self.db.execute(stmt)
        draft = res.scalar_one_or_none()
        if not draft:
            raise DraftNotFoundError(f"Outreach draft {draft_id} not found")

        prev_status = draft.status.value

        # 1. State transition validation: must be PENDING_APPROVAL
        if draft.status != OutreachDraftStatus.PENDING_APPROVAL:
            err_msg = (
                f"Cannot approve draft with status '{draft.status.value}'. "
                "Only drafts in PENDING_APPROVAL status can be approved."
            )
            await self._record_audit_event(
                action="approve_draft",
                draft_id=draft.id,
                owner_email=owner_email,
                status=AgentRunStatus.FAILED,
                input_data={"previous_status": prev_status},
                error_message=err_msg,
            )
            raise InvalidStateTransitionError(err_msg)

        # 2. Gate 1 check: lead must be APPROVED
        if not draft.lead or draft.lead.status != LeadStatus.APPROVED:
            current_lead_status = draft.lead.status.value if draft.lead else "none"
            err_msg = (
                f"Cannot approve draft for lead with status '{current_lead_status}'. "
                "Lead must have Gate 1 approval (LeadStatus.APPROVED) before Gate 2 draft approval."
            )
            await self._record_audit_event(
                action="approve_draft",
                draft_id=draft.id,
                owner_email=owner_email,
                status=AgentRunStatus.FAILED,
                input_data={"lead_id": str(draft.lead_id), "lead_status": current_lead_status},
                error_message=err_msg,
            )
            raise InvalidStateTransitionError(err_msg)

        # 3. Email verification check: must be MX_VERIFIED
        if not draft.lead or draft.lead.email_verification_status != EmailVerificationStatus.MX_VERIFIED:
            current_email_status = (
                draft.lead.email_verification_status.value if draft.lead else "none"
            )
            err_msg = (
                f"Cannot approve draft with recipient email status '{current_email_status}'. "
                "Email must be MX_VERIFIED before Gate 2 approval."
            )
            await self._record_audit_event(
                action="approve_draft",
                draft_id=draft.id,
                owner_email=owner_email,
                status=AgentRunStatus.FAILED,
                input_data={
                    "lead_id": str(draft.lead_id),
                    "email_verification_status": current_email_status,
                },
                error_message=err_msg,
            )
            raise InvalidStateTransitionError(err_msg)

        # Transition to APPROVED
        now = datetime.now(timezone.utc)
        draft.status = OutreachDraftStatus.APPROVED
        draft.approved_at = now
        draft.approved_by = owner_email
        draft.rejected_at = None
        draft.rejected_by = None
        draft.rejection_reason = None

        await self._record_audit_event(
            action="approve_draft",
            draft_id=draft.id,
            owner_email=owner_email,
            status=AgentRunStatus.COMPLETED,
            input_data={"previous_status": prev_status},
            output_data={
                "status": draft.status.value,
                "approved_at": now.isoformat(),
                "approved_by": owner_email,
            },
        )
        await self.db.flush()

        log.info(
            "Outreach draft approved by owner (Gate 2)",
            draft_id=str(draft.id),
            owner=owner_email,
            recipient=draft.recipient_email,
        )
        # Re-fetch cleanly with eager-loaded relationships
        stmt = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
            .where(OutreachDraft.id == draft_id)
        )
        res = await self.db.execute(stmt)
        refreshed = res.scalar_one()
        return self.enrich_draft_response(refreshed)

    async def reject_draft(
        self,
        draft_id: uuid.UUID,
        owner_email: str,
        reason: str,
    ) -> OutreachDraftResponse:
        """
        Owner rejects a draft (Gate 2).
        Enforces:
        - Draft exists
        - Draft is currently PENDING_APPROVAL
        - Reason is required and non-empty
        - Records rejected_at, rejected_by, rejection_reason, transitions to REJECTED
        - Emits an immutable audit record in agent_runs
        """
        stmt = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
            .where(OutreachDraft.id == draft_id)
        )
        res = await self.db.execute(stmt)
        draft = res.scalar_one_or_none()
        if not draft:
            raise DraftNotFoundError(f"Outreach draft {draft_id} not found")

        clean_reason = reason.strip() if reason else ""
        if not clean_reason:
            raise ValueError("Rejection reason cannot be empty")

        prev_status = draft.status.value

        # Must be PENDING_APPROVAL
        if draft.status != OutreachDraftStatus.PENDING_APPROVAL:
            err_msg = (
                f"Cannot reject draft with status '{draft.status.value}'. "
                "Only drafts in PENDING_APPROVAL status can be rejected."
            )
            await self._record_audit_event(
                action="reject_draft",
                draft_id=draft.id,
                owner_email=owner_email,
                status=AgentRunStatus.FAILED,
                input_data={"previous_status": prev_status, "reason": clean_reason},
                error_message=err_msg,
            )
            raise InvalidStateTransitionError(err_msg)

        # Transition to REJECTED
        now = datetime.now(timezone.utc)
        draft.status = OutreachDraftStatus.REJECTED
        draft.rejected_at = now
        draft.rejected_by = owner_email
        draft.rejection_reason = clean_reason
        draft.approved_at = None
        draft.approved_by = None

        await self._record_audit_event(
            action="reject_draft",
            draft_id=draft.id,
            owner_email=owner_email,
            status=AgentRunStatus.COMPLETED,
            input_data={"previous_status": prev_status, "reason": clean_reason},
            output_data={
                "status": draft.status.value,
                "rejected_at": now.isoformat(),
                "rejected_by": owner_email,
                "rejection_reason": clean_reason,
            },
        )
        await self.db.flush()

        log.info(
            "Outreach draft rejected by owner (Gate 2)",
            draft_id=str(draft.id),
            owner=owner_email,
            reason=clean_reason,
        )
        stmt = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
            .where(OutreachDraft.id == draft_id)
        )
        res = await self.db.execute(stmt)
        refreshed = res.scalar_one()
        return self.enrich_draft_response(refreshed)

    async def edit_draft(
        self,
        draft_id: uuid.UUID,
        owner_email: str,
        subject: Optional[str] = None,
        body_text: Optional[str] = None,
        body_html: Optional[str] = None,
    ) -> OutreachDraftResponse:
        """
        Owner edits draft subject or body.
        CRITICAL SAFETY RULE:
        Edits are ONLY allowed while the draft is PENDING_APPROVAL.
        Any edit on an APPROVED or REJECTED draft is strictly blocked.
        """
        stmt = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
            .where(OutreachDraft.id == draft_id)
        )
        res = await self.db.execute(stmt)
        draft = res.scalar_one_or_none()
        if not draft:
            raise DraftNotFoundError(f"Outreach draft {draft_id} not found")

        prev_status = draft.status.value

        # Must be in PENDING_APPROVAL
        if draft.status != OutreachDraftStatus.PENDING_APPROVAL:
            err_msg = (
                f"Cannot edit draft with status '{draft.status.value}'. "
                "Edits are strictly forbidden unless draft is PENDING_APPROVAL."
            )
            await self._record_audit_event(
                action="edit_draft",
                draft_id=draft.id,
                owner_email=owner_email,
                status=AgentRunStatus.FAILED,
                input_data={"previous_status": prev_status},
                error_message=err_msg,
            )
            raise InvalidStateTransitionError(err_msg)

        old_values = {
            "subject": draft.subject,
            "body_text": draft.body_text,
            "body_html": draft.body_html,
        }

        changes = {}
        if subject is not None and subject.strip():
            draft.subject = subject.strip()
            changes["subject"] = draft.subject
        if body_text is not None and body_text.strip():
            draft.body_text = body_text.strip()
            changes["body_text"] = draft.body_text
        if body_html is not None:
            draft.body_html = body_html.strip() if body_html.strip() else None
            changes["body_html"] = draft.body_html

        await self._record_audit_event(
            action="edit_draft",
            draft_id=draft.id,
            owner_email=owner_email,
            status=AgentRunStatus.COMPLETED,
            input_data={
                "previous_values": old_values,
                "changes": changes,
            },
            output_data={"status": draft.status.value},
        )
        await self.db.flush()

        log.info(
            "Outreach draft edited by owner",
            draft_id=str(draft.id),
            owner=owner_email,
            fields_changed=list(changes.keys()),
        )
        stmt = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
            .where(OutreachDraft.id == draft_id)
        )
        res = await self.db.execute(stmt)
        refreshed = res.scalar_one()
        return self.enrich_draft_response(refreshed)

    async def reset_draft_to_pending(
        self,
        draft_id: uuid.UUID,
        owner_email: str,
        reason: Optional[str] = None,
    ) -> OutreachDraftResponse:
        """
        Reset an APPROVED or REJECTED draft back to PENDING_APPROVAL.
        This enables modifying an approved draft without bypassing Gate 2,
        clearing previous approval metadata so fresh owner approval is mandatory.
        """
        stmt = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
            .where(OutreachDraft.id == draft_id)
        )
        res = await self.db.execute(stmt)
        draft = res.scalar_one_or_none()
        if not draft:
            raise DraftNotFoundError(f"Outreach draft {draft_id} not found")

        prev_status = draft.status.value
        if draft.status in (OutreachDraftStatus.SENT, OutreachDraftStatus.SUPPRESSED):
            err_msg = f"Cannot reset draft with immutable terminal status '{draft.status.value}'"
            await self._record_audit_event(
                action="reset_draft",
                draft_id=draft.id,
                owner_email=owner_email,
                status=AgentRunStatus.FAILED,
                input_data={"previous_status": prev_status},
                error_message=err_msg,
            )
            raise InvalidStateTransitionError(err_msg)

        draft.status = OutreachDraftStatus.PENDING_APPROVAL
        draft.approved_at = None
        draft.approved_by = None
        draft.rejected_at = None
        draft.rejected_by = None
        draft.rejection_reason = None

        await self._record_audit_event(
            action="reset_draft",
            draft_id=draft.id,
            owner_email=owner_email,
            status=AgentRunStatus.COMPLETED,
            input_data={"previous_status": prev_status, "reason": reason},
            output_data={"status": draft.status.value},
        )
        await self.db.flush()

        log.info(
            "Outreach draft returned to PENDING_APPROVAL",
            draft_id=str(draft.id),
            owner=owner_email,
            previous_status=prev_status,
        )
        stmt = (
            select(OutreachDraft)
            .options(
                selectinload(OutreachDraft.lead).selectinload(Lead.research)
            )
            .where(OutreachDraft.id == draft_id)
        )
        res = await self.db.execute(stmt)
        refreshed = res.scalar_one()
        return self.enrich_draft_response(refreshed)
