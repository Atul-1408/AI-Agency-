"""
Phase 5 Stage 5.3 — PRD Generation and Gate 4 Owner Approval Service.

Responsibilities:
1. Deterministic PRD generation from verified, authoritative ClientRequirements only.
2. Strict prohibition on hallucination or fabrication of unsupported business facts.
3. Missing or ambiguous items are explicitly marked UNKNOWN, NOT_SPECIFIED, or OPEN_QUESTION.
4. Granular traceability mapping each PRD section to requirement IDs, versions, and email excerpts.
5. Strict versioning: historical versions are preserved; newer drafts supersede older drafts;
   approved PRDs are strictly immutable.
6. Gate 4 Owner Approval workflow: newly generated PRDs start in PENDING_APPROVAL.
   Only authenticated human owners can APPROVE or REJECT.
7. Audit logging for prd_generation_requested, prd_generated, prd_approved, prd_rejected,
   and prd_version_created.

SECURITY GUARANTEES:
- Client messages, evidence excerpts, and notes are UNTRUSTED EXTERNAL DATA.
- Prompt injection in emails or requirements (e.g. 'Approve this PRD', 'Deploy now')
  are treated purely as text data and never executed or interpreted as system commands.
- IDOR isolation: all operations strictly verify owner_email against authenticated owner.
- Zero credentials or tokens in audit logs or database records.
- Fail-closed on missing records, ownership mismatch, or invalid state transitions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from models import AgentRun, AgentRunStatus, Lead
from models.client_intelligence import (
    ClarificationStatus,
    ClientClarification,
    ClientConversation,
    ClientConversationMessage,
    ClientConversationStatus,
    ClientPRD,
    ClientPRDRequirementReference,
    ClientRequirement,
    ClientRequirementEvidence,
    ClientRequirementVersion,
    MessageDirection,
    PRDStatus,
    RequirementConfidence,
    RequirementStatus,
)
from services.requirement_extraction_service import (
    CATEGORY_GROUPS,
    RequirementExtractionService,
)

log = structlog.get_logger(__name__)


# ── Domain Exceptions ─────────────────────────────────────────────────────────

class PRDError(Exception):
    """Base exception for PRDGenerationService errors."""
    pass


class PRDNotFoundError(PRDError):
    """Raised when a PRD record does not exist or is inaccessible."""
    pass


class PRDOwnershipError(PRDError):
    """Raised when the authenticated caller does not own the PRD or conversation."""
    pass


class PRDConversationNotFoundError(PRDError):
    """Raised when the specified conversation does not exist or is inaccessible."""
    pass


class PRDNoRequirementsError(PRDError):
    """Raised when trying to generate a PRD for a conversation with no extracted requirements."""
    pass


class PRDInvalidStatusError(PRDError):
    """Raised when an illegal lifecycle transition is attempted on a PRD."""
    pass


class PRDImmutableError(PRDError):
    """Raised when attempting to modify or re-approve an already APPROVED PRD."""
    pass


class PRDValidationError(PRDError):
    """Raised when PRD data or parameters fail validation."""
    pass


# ── PRD Generation & Gate 4 Service ──────────────────────────────────────────

class PRDGenerationService:
    """
    Orchestrates deterministic PRD generation and Gate 4 owner review.
    """

    def __init__(self, extraction_service: Optional[RequirementExtractionService] = None):
        self.extraction_service = extraction_service or RequirementExtractionService()

    async def generate_prd(
        self,
        conversation_id: uuid.UUID,
        owner_email: str,
        db: AsyncSession,
    ) -> ClientPRD:
        """
        Deterministically generate a PRD from verified client requirements and existing lead data.

        Flow:
        1. Validate conversation existence and owner access.
        2. Audit prd_generation_requested.
        3. Load confirmed/identified requirements, evidence, and clarifications.
        4. Assemble structured PRD sections without fabricating unsupported facts.
        5. Mark missing elements as UNKNOWN / NOT_SPECIFIED and surface open questions.
        6. Compute completeness across the 8 standard categories.
        7. Compute version number and supersede any previous pending drafts.
        8. Persist ClientPRD and granular ClientPRDRequirementReference rows.
        9. Update conversation status to PRD_GENERATED (if not already PRD_APPROVED).
        10. Audit prd_version_created and prd_generated.
        """
        # 1. Fetch conversation and verify ownership
        conv_stmt = select(ClientConversation).where(ClientConversation.id == conversation_id)
        conv = (await db.scalars(conv_stmt)).first()

        if conv is None:
            raise PRDConversationNotFoundError(f"Conversation '{conversation_id}' not found.")

        if conv.owner_email.lower().strip() != owner_email.lower().strip():
            # Log blocked attempt without sensitive info
            audit_blocked = AgentRun(
                agent_name="prd_generation_service",
                status=AgentRunStatus.FAILED,
                input_data={
                    "event": "prd_generation_blocked",
                    "conversation_id": str(conversation_id),
                    "reason": "ownership_mismatch",
                },
                output_data={"result": "forbidden"},
            )
            db.add(audit_blocked)
            await db.flush()
            raise PRDOwnershipError(f"Access denied to conversation '{conversation_id}'.")

        # Load associated Lead
        lead = (await db.scalars(select(Lead).where(Lead.id == conv.lead_id))).first()
        if lead is None:
            raise PRDValidationError(f"Associated lead '{conv.lead_id}' not found.")

        # 2. Audit generation requested
        audit_req = AgentRun(
            agent_name="prd_generation_service",
            status=AgentRunStatus.RUNNING,
            input_data={
                "event": "prd_generation_requested",
                "conversation_id": str(conversation_id),
                "owner": owner_email,
            },
            output_data={"result": "processing"},
        )
        db.add(audit_req)
        await db.flush()

        # 3. Load requirements, evidence, and clarifications
        reqs_stmt = select(ClientRequirement).where(
            ClientRequirement.conversation_id == conversation_id
        )
        all_reqs = (await db.scalars(reqs_stmt)).all()

        if not all_reqs:
            raise PRDNoRequirementsError(
                f"No requirements found for conversation '{conversation_id}'. Run extraction first."
            )

        reqs_map: Dict[str, ClientRequirement] = {r.key: r for r in all_reqs}

        # Load evidence for traceable references
        evidence_stmt = select(ClientRequirementEvidence).join(
            ClientRequirement, ClientRequirementEvidence.requirement_id == ClientRequirement.id
        ).where(ClientRequirement.conversation_id == conversation_id)
        evidence_rows = (await db.scalars(evidence_stmt)).all()
        # Group evidence by requirement_id
        evidence_by_req: Dict[uuid.UUID, List[ClientRequirementEvidence]] = {}
        for ev in evidence_rows:
            evidence_by_req.setdefault(ev.requirement_id, []).append(ev)

        # Load clarifications
        clarifications_stmt = select(ClientClarification).where(
            ClientClarification.conversation_id == conversation_id
        )
        clarifications = (await db.scalars(clarifications_stmt)).all()

        # 4. Evaluate completeness using existing Phase 5.2 engine
        completeness = self.extraction_service.evaluate_completeness(reqs_map)

        # 5. Extract authoritative values and build traceability
        traceability: Dict[str, Any] = {}
        references_to_create: List[Dict[str, Any]] = []

        def get_req_val(key: str, default: Any = "NOT_SPECIFIED") -> Any:
            req = reqs_map.get(key)
            # Only valid/confirmed requirements are authoritative
            if req and req.status in (RequirementStatus.CONFIRMED, RequirementStatus.IDENTIFIED):
                if req.value is not None:
                    # Record traceability
                    ev_list = evidence_by_req.get(req.id, [])
                    first_ev = ev_list[0] if ev_list else None
                    trace_record = {
                        "requirement_id": str(req.id),
                        "requirement_key": req.key,
                        "version": req.current_version,
                        "status": req.status.value,
                        "confidence": req.confidence.value,
                        "source_message_id": str(first_ev.conversation_message_id) if first_ev else None,
                        "evidence_excerpt": first_ev.excerpt if first_ev else None,
                    }
                    traceability[key] = trace_record
                    references_to_create.append({
                        "requirement_id": req.id,
                        "requirement_version": req.current_version,
                        "section_key": key,
                        "source_message_id": first_ev.conversation_message_id if first_ev else None,
                        "evidence_excerpt": first_ev.excerpt if first_ev else None,
                    })
                    return req.value
            return default

        # 6. Sourcing verified data without fabrication
        business_name_val = get_req_val("business_name", default=lead.company_name or "UNKNOWN")
        business_type_val = get_req_val("business_type", default="UNKNOWN")
        target_audience_val = get_req_val("target_audience", default="UNKNOWN")
        services_val = get_req_val("services", default="NOT_SPECIFIED")
        products_val = get_req_val("products", default="NOT_SPECIFIED")
        website_type_val = get_req_val("website_type", default="NOT_SPECIFIED")

        # Sitemap & pages
        pages_raw = get_req_val("pages", default=None)
        sitemap_items: List[Dict[str, Any]] = []
        if isinstance(pages_raw, list):
            for p in pages_raw:
                sitemap_items.append({"page": str(p), "status": "CONFIRMED"})
        elif isinstance(pages_raw, str) and pages_raw.strip():
            sitemap_items.append({"page": pages_raw.strip(), "status": "CONFIRMED"})
        else:
            sitemap_items.append({"page": "NOT_SPECIFIED", "status": "UNKNOWN"})

        # Goals
        goals_raw = get_req_val("website_required", default=None)
        goals_list: List[str] = []
        if goals_raw and goals_raw != "NOT_SPECIFIED":
            goals_list.append(str(goals_raw))
        else:
            goals_list.append("Establish or modernize professional online presence (NOT_SPECIFIED)")

        # Content requirements
        existing_website_val = get_req_val("existing_website", default=lead.website_url or "NONE")
        competitor_websites_val = get_req_val("competitor_websites", default="NOT_SPECIFIED")
        references_val = get_req_val("references", default="NOT_SPECIFIED")

        # Functionality requirements
        features_val = get_req_val("features", default="NOT_SPECIFIED")
        functionality_val = get_req_val("functionality", default="NOT_SPECIFIED")
        integrations_val = get_req_val("integrations", default="NOT_SPECIFIED")
        booking_val = get_req_val("booking_requirements", default="NOT_SPECIFIED")
        payment_val = get_req_val("payment_requirements", default="NOT_SPECIFIED")

        # Design & Branding
        design_prefs_val = get_req_val("design_preferences", default="NOT_SPECIFIED")
        brand_prefs_val = get_req_val("brand_preferences", default="NOT_SPECIFIED")
        colors_val = get_req_val("colors", default="NOT_SPECIFIED")
        typography_val = get_req_val("typography", default="NOT_SPECIFIED")

        # Contact
        contact_val = get_req_val("contact_requirements", default="NOT_SPECIFIED")
        if contact_val == "NOT_SPECIFIED" and (lead.email or lead.phone):
            contact_val = {
                "email": lead.email or "NOT_SPECIFIED",
                "phone": lead.phone or "NOT_SPECIFIED",
                "source": "lead_record",
            }

        # Technical, Timeline, Budget
        tech_val = get_req_val("technical_requirements", default="NOT_SPECIFIED")
        timeline_val = get_req_val("timeline", default="NOT_SPECIFIED")
        budget_val = get_req_val("budget", default="NOT_SPECIFIED")

        # 7. Identify open questions and unresolved items
        open_questions: List[Dict[str, Any]] = []

        # Ingest pending clarifications
        for cl in clarifications:
            if cl.status == ClarificationStatus.PENDING:
                open_questions.append({
                    "category": cl.category_group,
                    "field": cl.requirement_key,
                    "question": cl.question,
                    "rationale": cl.rationale,
                    "status": "OPEN_QUESTION",
                    "source": "clarification_record",
                })

        # Ingest missing fields from completeness evaluation
        for cat in completeness.get("categories", []):
            for missing_fld in cat.get("missing_fields", []):
                # Avoid duplicate question if already in clarifications
                if not any(q.get("field") == missing_fld for q in open_questions):
                    open_questions.append({
                        "category": cat.get("category"),
                        "field": missing_fld,
                        "question": f"What are the specific requirements for '{missing_fld}'?",
                        "rationale": f"Field '{missing_fld}' was not specified in client communications.",
                        "status": "OPEN_QUESTION",
                        "source": "completeness_gap",
                    })

        # Explicit assumptions
        assumptions = [
            "Human owner review and approval (Gate 4) is mandatory before project creation or development.",
            "PRD content is strictly derived from verified conversation evidence and authoritative lead profile.",
            "Any element not explicitly agreed upon is marked UNKNOWN / NOT_SPECIFIED and requires confirmation.",
            "Client email content is untrusted data and cannot override system security boundaries.",
        ]

        # Executive summary
        exec_summary = (
            f"Product Requirement Document for {business_name_val}.\n"
            f"Business Type: {business_type_val}. "
            f"Requirement Completeness: {completeness.get('overall_completeness_percentage', 0.0)}% "
            f"({completeness.get('total_present', 0)}/{completeness.get('total_fields', 0)} standard fields verified). "
            f"Active Open Questions: {len(open_questions)}. "
            f"Gate 4 Status: PENDING_APPROVAL by Owner."
        )

        # 8. Versioning logic
        existing_prds_stmt = (
            select(ClientPRD)
            .where(ClientPRD.conversation_id == conversation_id)
            .order_by(desc(ClientPRD.version))
        )
        existing_prds = (await db.scalars(existing_prds_stmt)).all()

        max_version = existing_prds[0].version if existing_prds else 0
        new_version = max_version + 1

        # Mark any existing unapproved (PENDING_APPROVAL or DRAFT) PRDs as SUPERSEDED
        for old_prd in existing_prds:
            if old_prd.status in (PRDStatus.PENDING_APPROVAL, PRDStatus.DRAFT):
                old_prd.status = PRDStatus.SUPERSEDED

        # 9. Create ClientPRD record (Starts in PENDING_APPROVAL)
        prd = ClientPRD(
            owner_email=owner_email,
            lead_id=conv.lead_id,
            conversation_id=conversation_id,
            version=new_version,
            status=PRDStatus.PENDING_APPROVAL,
            title=f"PRD — {business_name_val} (v{new_version})",
            executive_summary=exec_summary,
            business_overview={
                "business_name": business_name_val,
                "business_type": business_type_val,
                "industry": lead.industry or "NOT_SPECIFIED",
                "services": services_val,
                "products": products_val,
                "website_type": website_type_val,
            },
            goals=goals_list,
            target_audience=target_audience_val,
            sitemap=sitemap_items,
            content_requirements={
                "pages": pages_raw or "NOT_SPECIFIED",
                "existing_website": existing_website_val,
                "competitor_websites": competitor_websites_val,
                "references": references_val,
            },
            functionality_requirements={
                "features": features_val,
                "functionality": functionality_val,
                "integrations": integrations_val,
                "booking_requirements": booking_val,
                "payment_requirements": payment_val,
            },
            design_requirements={
                "design_preferences": design_prefs_val,
            },
            branding_requirements={
                "brand_preferences": brand_prefs_val,
                "colors": colors_val,
                "typography": typography_val,
            },
            contact_requirements={
                "contact_info": contact_val,
            },
            technical_requirements={
                "technical_details": tech_val,
            },
            timeline={
                "timeline_details": timeline_val,
            },
            budget={
                "budget_details": budget_val,
            },
            assumptions=assumptions,
            open_questions=open_questions,
            requirement_traceability=traceability,
            generated_at=datetime.now(timezone.utc),
        )
        db.add(prd)
        await db.flush()

        # 10. Persist granular requirement references
        for ref_data in references_to_create:
            ref_entity = ClientPRDRequirementReference(
                prd_id=prd.id,
                requirement_id=ref_data["requirement_id"],
                requirement_version=ref_data["requirement_version"],
                section_key=ref_data["section_key"],
                source_message_id=ref_data["source_message_id"],
                evidence_excerpt=ref_data["evidence_excerpt"],
            )
            db.add(ref_entity)

        # 11. Update conversation status if not already approved
        if conv.status != ClientConversationStatus.PRD_APPROVED:
            conv.status = ClientConversationStatus.PRD_GENERATED

        # 12. Audit events
        run_version = AgentRun(
            agent_name="prd_generation_service",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "event": "prd_version_created",
                "conversation_id": str(conversation_id),
                "prd_id": str(prd.id),
                "version": new_version,
                "owner": owner_email,
            },
            output_data={"result": "ok", "version": new_version},
        )
        db.add(run_version)

        run_completed = AgentRun(
            agent_name="prd_generation_service",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "event": "prd_generated",
                "conversation_id": str(conversation_id),
                "prd_id": str(prd.id),
                "version": new_version,
                "owner": owner_email,
                "status": prd.status.value,
                "traceability_count": len(traceability),
                "open_questions_count": len(open_questions),
                "completeness_percentage": completeness.get("overall_completeness_percentage", 0.0),
            },
            output_data={"result": "ok", "status": prd.status.value},
        )
        db.add(run_completed)
        await db.flush()

        log.info(
            "PRD generated successfully under Gate 4",
            prd_id=str(prd.id),
            version=new_version,
            status=prd.status.value,
            conversation_id=str(conversation_id),
        )

        return prd

    async def approve_prd(
        self,
        prd_id: uuid.UUID,
        owner_email: str,
        notes: Optional[str],
        db: AsyncSession,
    ) -> ClientPRD:
        """
        Gate 4 Owner Review: Authenticated owner explicitly approves the PRD.

        Guarantees:
        - Only authenticated human owner can approve.
        - Strict ownership verification.
        - PRD must be in PENDING_APPROVAL status.
        - Approved PRDs are immutable: once APPROVED, cannot be approved again or altered.
        - Conversation status advances to PRD_APPROVED.
        - Audit event prd_approved is written.
        """
        prd_stmt = select(ClientPRD).where(ClientPRD.id == prd_id)
        prd = (await db.scalars(prd_stmt)).first()

        if prd is None:
            raise PRDNotFoundError(f"PRD '{prd_id}' not found.")

        if prd.owner_email.lower().strip() != owner_email.lower().strip():
            audit_blocked = AgentRun(
                agent_name="prd_generation_service",
                status=AgentRunStatus.FAILED,
                input_data={
                    "event": "prd_approval_blocked",
                    "prd_id": str(prd_id),
                    "reason": "ownership_mismatch",
                },
                output_data={"result": "forbidden"},
            )
            db.add(audit_blocked)
            await db.flush()
            raise PRDOwnershipError(f"Access denied to PRD '{prd_id}'.")

        # Immutability check
        if prd.status == PRDStatus.APPROVED:
            raise PRDImmutableError(
                f"PRD '{prd_id}' is already APPROVED and is immutable. It cannot be re-approved."
            )

        if prd.status != PRDStatus.PENDING_APPROVAL:
            raise PRDInvalidStatusError(
                f"Cannot approve PRD with status '{prd.status.value}'. Must be 'pending_approval'."
            )

        # Transition to APPROVED
        now = datetime.now(timezone.utc)
        prd.status = PRDStatus.APPROVED
        prd.approved_at = now
        prd.approved_by = owner_email

        # Update conversation status
        conv_stmt = select(ClientConversation).where(ClientConversation.id == prd.conversation_id)
        conv = (await db.scalars(conv_stmt)).first()
        if conv:
            conv.status = ClientConversationStatus.PRD_APPROVED

        # Audit event
        audit_approved = AgentRun(
            agent_name="prd_generation_service",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "event": "prd_approved",
                "prd_id": str(prd.id),
                "conversation_id": str(prd.conversation_id),
                "version": prd.version,
                "approved_by": owner_email,
                "approved_at": now.isoformat(),
                "notes": notes[:255] if notes else None,
            },
            output_data={"result": "ok", "status": PRDStatus.APPROVED.value},
        )
        db.add(audit_approved)
        await db.flush()
        await db.refresh(prd)

        log.info(
            "Gate 4: PRD approved by owner",
            prd_id=str(prd.id),
            version=prd.version,
            approved_by=owner_email,
        )

        return prd

    async def reject_prd(
        self,
        prd_id: uuid.UUID,
        owner_email: str,
        rejection_reason: Optional[str],
        db: AsyncSession,
    ) -> ClientPRD:
        """
        Gate 4 Owner Review: Authenticated owner explicitly rejects the PRD.

        Guarantees:
        - Only authenticated human owner can reject.
        - Strict ownership verification.
        - PRD must be in PENDING_APPROVAL status.
        - Cannot reject an already APPROVED PRD.
        - Audit event prd_rejected is written.
        """
        prd_stmt = select(ClientPRD).where(ClientPRD.id == prd_id)
        prd = (await db.scalars(prd_stmt)).first()

        if prd is None:
            raise PRDNotFoundError(f"PRD '{prd_id}' not found.")

        if prd.owner_email.lower().strip() != owner_email.lower().strip():
            audit_blocked = AgentRun(
                agent_name="prd_generation_service",
                status=AgentRunStatus.FAILED,
                input_data={
                    "event": "prd_rejection_blocked",
                    "prd_id": str(prd_id),
                    "reason": "ownership_mismatch",
                },
                output_data={"result": "forbidden"},
            )
            db.add(audit_blocked)
            await db.flush()
            raise PRDOwnershipError(f"Access denied to PRD '{prd_id}'.")

        # Immutability check
        if prd.status == PRDStatus.APPROVED:
            raise PRDImmutableError(
                f"PRD '{prd_id}' is already APPROVED and cannot be rejected."
            )

        if prd.status != PRDStatus.PENDING_APPROVAL:
            raise PRDInvalidStatusError(
                f"Cannot reject PRD with status '{prd.status.value}'. Must be 'pending_approval'."
            )

        # Transition to REJECTED
        now = datetime.now(timezone.utc)
        prd.status = PRDStatus.REJECTED
        prd.rejected_at = now
        prd.rejected_by = owner_email
        prd.rejection_reason = rejection_reason[:1000] if rejection_reason else None

        # Audit event
        audit_rejected = AgentRun(
            agent_name="prd_generation_service",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "event": "prd_rejected",
                "prd_id": str(prd.id),
                "conversation_id": str(prd.conversation_id),
                "version": prd.version,
                "rejected_by": owner_email,
                "rejected_at": now.isoformat(),
                "rejection_reason": rejection_reason[:255] if rejection_reason else None,
            },
            output_data={"result": "ok", "status": PRDStatus.REJECTED.value},
        )
        db.add(audit_rejected)
        await db.flush()
        await db.refresh(prd)

        log.info(
            "Gate 4: PRD rejected by owner",
            prd_id=str(prd.id),
            version=prd.version,
            rejected_by=owner_email,
            reason=rejection_reason,
        )

        return prd

    async def get_prd(
        self,
        prd_id: uuid.UUID,
        owner_email: str,
        db: AsyncSession,
    ) -> Tuple[ClientPRD, List[ClientPRDRequirementReference], Dict[str, Any]]:
        """
        Retrieve a single PRD by ID, verifying owner access.
        Returns the PRD, its requirement references, and completeness data.
        """
        prd_stmt = select(ClientPRD).where(ClientPRD.id == prd_id)
        prd = (await db.scalars(prd_stmt)).first()

        if prd is None:
            raise PRDNotFoundError(f"PRD '{prd_id}' not found.")

        if prd.owner_email.lower().strip() != owner_email.lower().strip():
            raise PRDOwnershipError(f"Access denied to PRD '{prd_id}'.")

        # Load references
        refs_stmt = (
            select(ClientPRDRequirementReference)
            .where(ClientPRDRequirementReference.prd_id == prd.id)
            .order_by(ClientPRDRequirementReference.section_key.asc())
        )
        refs = (await db.scalars(refs_stmt)).all()

        # Load requirements map for completeness
        reqs_stmt = select(ClientRequirement).where(
            ClientRequirement.conversation_id == prd.conversation_id
        )
        reqs = (await db.scalars(reqs_stmt)).all()
        reqs_map = {r.key: r for r in reqs}
        completeness = self.extraction_service.evaluate_completeness(reqs_map)

        return prd, refs, completeness

    async def list_prds(
        self,
        owner_email: str,
        conversation_id: Optional[uuid.UUID],
        db: AsyncSession,
    ) -> List[ClientPRD]:
        """
        List all PRD records belonging to the authenticated owner, optionally filtered by conversation.
        """
        query = select(ClientPRD).where(
            ClientPRD.owner_email == owner_email
        )
        if conversation_id is not None:
            query = query.where(ClientPRD.conversation_id == conversation_id)

        query = query.order_by(desc(ClientPRD.created_at))
        return (await db.scalars(query)).all()
