"""
Phase 3 — Stage 3.3: Outreach Safety Controller.

Enforces strictly approved Phase 3 safety policies before any outreach email can be dispatched:
1. Maximum 20 new leads/day (MAX_NEW_LEADS_PER_DAY = 20)
2. Maximum 30 total sends/day (MAX_DAILY_SENDS = 30)
3. Minimum 120 seconds between sends to the same recipient domain (DOMAIN_PACING_SECONDS = 120)
4. Suppression enforcement for email and domain (SuppressionRecord)
5. Gate 2 human approval required before sending (OutreachDraft.status == APPROVED)
6. MX_VERIFIED recipient email required (EmailVerificationStatus.MX_VERIFIED)
7. Gmail health and connection must be valid before dispatch
8. Circuit breaker operational states: NORMAL, WARNING, THROTTLED, PAUSED
9. Fail-closed architecture: ANY failed safety condition or unhandled exception blocks dispatch
10. Never bypass safety checks; audit all blocked attempts in SendAttempt table.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from core.config import settings
from models import (
    CircuitBreakerState,
    DeliveryEvent,
    DeliveryEventType,
    EmailVerificationStatus,
    GmailAccount,
    GmailConnectionStatus,
    Lead,
    LeadStatus,
    OutreachDraft,
    OutreachDraftStatus,
    OutreachMessage,
    OutreachMessageStatus,
    SendAttempt,
    SendAttemptResult,
    SuppressionRecord,
)
from services.discovery.base import normalize_domain

log = structlog.get_logger(__name__)


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class CircuitBreaker:
    """
    Delivery safety circuit breaker tracking delivery errors and bounce rates.
    States:
      - NORMAL: Clean operations, zero or low error rate (< 2%).
      - WARNING: Elevated bounces or errors (2% - 5%).
      - THROTTLED: High error rate (5% - 10%). Enforces safety cool-down.
      - PAUSED: Critical failure (> 10% bounces or consecutive critical errors). Hard stop.
    """

    def __init__(
        self,
        warning_threshold: float = 0.02,
        throttle_threshold: float = 0.05,
        pause_threshold: float = 0.10,
        consecutive_failure_limit: int = 3,
    ):
        self.warning_threshold = warning_threshold
        self.throttle_threshold = throttle_threshold
        self.pause_threshold = pause_threshold
        self.consecutive_failure_limit = consecutive_failure_limit
        self._manual_state: Optional[CircuitBreakerState] = None
        self._manual_reason: Optional[str] = None

    @property
    def state(self) -> CircuitBreakerState:
        return self._manual_state or CircuitBreakerState.NORMAL

    def set_state(self, new_state: CircuitBreakerState, reason: str = "") -> None:
        """Manually transition circuit breaker state (e.g. owner pause or manual reset)."""
        self._manual_state = new_state
        self._manual_reason = reason
        log.info("Circuit breaker manual state transition", state=new_state.value, reason=reason)

    def reset(self) -> None:
        """Reset circuit breaker to NORMAL operational state."""
        self._manual_state = CircuitBreakerState.NORMAL
        self._manual_reason = None
        log.info("Circuit breaker reset to NORMAL")

    def trip(self, reason: str) -> None:
        """Trip circuit breaker into PAUSED emergency state."""
        self.set_state(CircuitBreakerState.PAUSED, reason=reason)

    def throttle(self, reason: str) -> None:
        """Trip circuit breaker into THROTTLED state."""
        self.set_state(CircuitBreakerState.THROTTLED, reason=reason)

    async def evaluate_dynamic_state(self, db: AsyncSession, lookback_window: int = 50) -> CircuitBreakerState:
        """
        Dynamically evaluate recent delivery events and failure rates over recent attempts.
        """
        if self._manual_state is not None:
            return self._manual_state

        # Check last N delivery events
        stmt = (
            select(DeliveryEvent)
            .order_by(DeliveryEvent.created_at.desc())
            .limit(lookback_window)
        )
        res = await db.execute(stmt)
        events = res.scalars().all()

        if not events:
            return CircuitBreakerState.NORMAL

        bounces = sum(1 for e in events if e.event_type in (DeliveryEventType.BOUNCED, DeliveryEventType.FAILED))
        bounce_rate = bounces / len(events)

        # Check consecutive failures
        consecutive_failures = 0
        for e in events:
            if e.event_type in (DeliveryEventType.BOUNCED, DeliveryEventType.FAILED):
                consecutive_failures += 1
            else:
                break

        if bounce_rate >= self.pause_threshold or consecutive_failures >= self.consecutive_failure_limit:
            log.warning("Circuit breaker dynamically tripped to PAUSED", bounce_rate=bounce_rate, consecutive=consecutive_failures)
            return CircuitBreakerState.PAUSED
        elif bounce_rate >= self.throttle_threshold:
            return CircuitBreakerState.THROTTLED
        elif bounce_rate >= self.warning_threshold:
            return CircuitBreakerState.WARNING

        return CircuitBreakerState.NORMAL

    def permits_send(self, current_state: CircuitBreakerState) -> Tuple[bool, Optional[str]]:
        """Determine if the circuit breaker permits email dispatch."""
        if current_state == CircuitBreakerState.PAUSED:
            reason = self._manual_reason or "Circuit breaker is PAUSED due to elevated bounce or delivery failure threshold"
            return False, reason
        elif current_state == CircuitBreakerState.THROTTLED:
            reason = self._manual_reason or "Circuit breaker is THROTTLED. Delivery pacing constrained"
            return False, reason
        return True, None


# ── Safety Check Result ───────────────────────────────────────────────────────

@dataclass
class SafetyCheckResult:
    allowed: bool
    violations: List[str] = field(default_factory=list)
    blocked_reason: Optional[str] = None
    circuit_breaker_state: CircuitBreakerState = CircuitBreakerState.NORMAL
    checks_passed: Dict[str, bool] = field(default_factory=dict)
    send_attempt_id: Optional[uuid.UUID] = None
    daily_sends_count: int = 0
    new_leads_count: int = 0
    pacing_elapsed_seconds: Optional[float] = None


# ── Safety Controller ─────────────────────────────────────────────────────────

class SafetyController:
    """
    Central Safety Controller for Phase 3 Outreach.
    Enforces all quotas, pacing, suppression, Gate 2 approvals, and health checks before sending.
    Always fails closed.
    """

    def __init__(self, circuit_breaker: Optional[CircuitBreaker] = None):
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    # ── Individual Policy Check Helpers ───────────────────────────────────────

    async def check_suppression(
        self,
        db: AsyncSession,
        email: str,
        domain: Optional[str] = None,
    ) -> Optional[SuppressionRecord]:
        """
        Check if an email or domain is on the suppression list.
        """
        clean_email = email.strip().lower()
        clean_domain = (domain or clean_email.split("@")[-1]).strip().lower()

        stmt = select(SuppressionRecord).where(
            (func.lower(SuppressionRecord.email) == clean_email)
            | (func.lower(SuppressionRecord.domain) == clean_domain)
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def get_daily_sends_count(self, db: AsyncSession, target_date: Optional[datetime] = None) -> int:
        """Count total successful outreach messages sent today (UTC)."""
        ref_time = target_date or datetime.now(timezone.utc)
        day_start = ref_time.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        stmt = select(func.count(OutreachMessage.id)).where(
            OutreachMessage.sent_at >= day_start,
            OutreachMessage.sent_at < day_end,
            OutreachMessage.status == OutreachMessageStatus.SENT,
        )
        res = await db.execute(stmt)
        return res.scalar_one() or 0

    async def get_daily_new_leads_count(self, db: AsyncSession, target_date: Optional[datetime] = None) -> int:
        """Count distinct leads messaged today (UTC)."""
        ref_time = target_date or datetime.now(timezone.utc)
        day_start = ref_time.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        stmt = select(func.count(func.distinct(OutreachMessage.lead_id))).where(
            OutreachMessage.sent_at >= day_start,
            OutreachMessage.sent_at < day_end,
            OutreachMessage.status == OutreachMessageStatus.SENT,
        )
        res = await db.execute(stmt)
        return res.scalar_one() or 0

    async def get_domain_pacing(
        self,
        db: AsyncSession,
        domain: str,
        now: Optional[datetime] = None,
    ) -> Tuple[Optional[float], bool]:
        """
        Check seconds elapsed since the most recent message or send attempt to this domain.
        Returns: (elapsed_seconds, is_allowed)
        """
        ref_time = now or datetime.now(timezone.utc)
        clean_domain = normalize_domain(domain)

        # 1. Check most recent sent OutreachMessage for this domain
        stmt_msg = (
            select(OutreachMessage.sent_at)
            .join(Lead, Lead.id == OutreachMessage.lead_id)
            .where(
                (func.lower(Lead.domain) == clean_domain)
                | (func.lower(OutreachMessage.recipient_email).endswith(f"@{clean_domain}"))
            )
            .order_by(OutreachMessage.sent_at.desc())
            .limit(1)
        )
        res_msg = await db.execute(stmt_msg)
        last_sent = res_msg.scalar_one_or_none()

        # 2. Check most recent successful SendAttempt for this domain
        stmt_attempt = (
            select(SendAttempt.attempted_at)
            .join(Lead, Lead.id == SendAttempt.lead_id)
            .where(
                (func.lower(Lead.domain) == clean_domain)
                | (func.lower(SendAttempt.recipient_email).endswith(f"@{clean_domain}")),
                SendAttempt.result == SendAttemptResult.SUCCESS,
            )
            .order_by(SendAttempt.attempted_at.desc())
            .limit(1)
        )
        res_attempt = await db.execute(stmt_attempt)
        last_attempt = res_attempt.scalar_one_or_none()

        timestamps = [t for t in [last_sent, last_attempt] if t is not None]
        if not timestamps:
            return None, True

        most_recent = max(timestamps)
        # Handle naive timestamps from SQLite if necessary
        if most_recent.tzinfo is None:
            most_recent = most_recent.replace(tzinfo=timezone.utc)

        elapsed = (ref_time - most_recent).total_seconds()
        is_allowed = elapsed >= settings.DOMAIN_PACING_SECONDS
        return elapsed, is_allowed

    async def check_gmail_health(self, db: AsyncSession) -> Tuple[bool, Optional[str]]:
        """
        Verify that a connected, healthy Gmail account is configured in the database.
        """
        stmt = select(GmailAccount).where(
            GmailAccount.connection_status == GmailConnectionStatus.CONNECTED
        )
        res = await db.execute(stmt)
        account = res.scalar_one_or_none()

        if not account:
            return False, "No active connected Gmail account found (status must be CONNECTED)"

        return True, None

    # ── Main Comprehensive Validation Pipeline ────────────────────────────────

    async def validate_send(
        self,
        db: AsyncSession,
        draft_id: uuid.UUID,
        record_blocked_attempt: bool = True,
        override_now: Optional[datetime] = None,
    ) -> SafetyCheckResult:
        """
        Execute full 12-point safety validation for an outreach draft.
        Fails closed on any violation or unhandled exception.
        """
        now = override_now or datetime.now(timezone.utc)
        violations: List[str] = []
        checks_passed: Dict[str, bool] = {}
        target_lead: Optional[Lead] = None
        target_draft: Optional[OutreachDraft] = None
        cb_state = CircuitBreakerState.NORMAL
        daily_sends = 0
        new_leads = 0
        pacing_elapsed: Optional[float] = None

        try:
            # ── 1. Draft Existence ────────────────────────────────────────────
            stmt_draft = select(OutreachDraft).where(OutreachDraft.id == draft_id)
            res_draft = await db.execute(stmt_draft)
            target_draft = res_draft.scalar_one_or_none()

            if not target_draft:
                violations.append(f"Outreach draft {draft_id} does not exist.")
                checks_passed["draft_exists"] = False
                return SafetyCheckResult(
                    allowed=False,
                    violations=violations,
                    blocked_reason="; ".join(violations),
                    checks_passed=checks_passed,
                )
            checks_passed["draft_exists"] = True

            # ── 2. Lead Existence & Status ────────────────────────────────────
            stmt_lead = (
                select(Lead)
                .options(selectinload(Lead.research))
                .where(Lead.id == target_draft.lead_id)
            )
            res_lead = await db.execute(stmt_lead)
            target_lead = res_lead.scalar_one_or_none()

            if not target_lead:
                violations.append(f"Associated lead {target_draft.lead_id} does not exist.")
                checks_passed["lead_exists"] = False
            else:
                checks_passed["lead_exists"] = True
                if target_lead.status != LeadStatus.APPROVED:
                    violations.append(
                        f"Gate 1 violation: Lead '{target_lead.company_name}' is not in APPROVED status (current: {target_lead.status.value})."
                    )
                    checks_passed["lead_approved"] = False
                else:
                    checks_passed["lead_approved"] = True

            # ── 3. Gate 2 Human Owner Approval ────────────────────────────────
            # Draft must be explicitly APPROVED by owner
            is_approved = (
                target_draft.status == OutreachDraftStatus.APPROVED
                or (target_draft.approved_at is not None and bool(target_draft.approved_by))
            )
            if not is_approved:
                violations.append(
                    f"Gate 2 violation: Draft has not received owner approval (current status: {target_draft.status.value})."
                )
                checks_passed["gate_2_approved"] = False
            else:
                checks_passed["gate_2_approved"] = True

            # ── 4. MX Verification ────────────────────────────────────────────
            if not target_lead or target_lead.email_verification_status != EmailVerificationStatus.MX_VERIFIED:
                current_ver = target_lead.email_verification_status.value if target_lead else "unknown"
                violations.append(
                    f"MX verification failure: Recipient email '{target_draft.recipient_email}' is not MX_VERIFIED (status: {current_ver})."
                )
                checks_passed["mx_verified"] = False
            else:
                checks_passed["mx_verified"] = True

            # ── 5. Suppression Enforcement ────────────────────────────────────
            domain = normalize_domain(
                target_lead.domain if target_lead else target_draft.recipient_email.split("@")[-1]
            )
            suppression_match = await self.check_suppression(
                db, email=target_draft.recipient_email, domain=domain
            )
            if suppression_match:
                violations.append(
                    f"Suppression violation: Recipient '{target_draft.recipient_email}' or domain '{domain}' is suppressed (reason: {suppression_match.reason.value})."
                )
                checks_passed["not_suppressed"] = False
            else:
                checks_passed["not_suppressed"] = True

            # ── 6. Total Daily Send Quota (Max 30) ─────────────────────────────
            daily_sends = await self.get_daily_sends_count(db, target_date=now)
            if daily_sends >= settings.MAX_DAILY_SENDS:
                violations.append(
                    f"Daily send quota exceeded: {daily_sends}/{settings.MAX_DAILY_SENDS} sends completed today."
                )
                checks_passed["daily_send_quota"] = False
            else:
                checks_passed["daily_send_quota"] = True

            # ── 7. New Lead Daily Quota (Max 20) ──────────────────────────────
            new_leads = await self.get_daily_new_leads_count(db, target_date=now)
            # Check if this lead was already contacted today
            already_contacted_today = False
            if target_lead:
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                stmt_contacted = select(OutreachMessage.id).where(
                    OutreachMessage.lead_id == target_lead.id,
                    OutreachMessage.sent_at >= day_start,
                    OutreachMessage.status == OutreachMessageStatus.SENT,
                ).limit(1)
                res_contacted = await db.execute(stmt_contacted)
                already_contacted_today = res_contacted.scalar_one_or_none() is not None

            if not already_contacted_today and new_leads >= settings.MAX_NEW_LEADS_PER_DAY:
                violations.append(
                    f"New lead daily quota exceeded: {new_leads}/{settings.MAX_NEW_LEADS_PER_DAY} distinct leads messaged today."
                )
                checks_passed["new_lead_quota"] = False
            else:
                checks_passed["new_lead_quota"] = True

            # ── 8. Same-Domain Pacing (Min 120s) ───────────────────────────────
            pacing_elapsed, pacing_allowed = await self.get_domain_pacing(db, domain=domain, now=now)
            if not pacing_allowed and pacing_elapsed is not None:
                remaining = round(settings.DOMAIN_PACING_SECONDS - pacing_elapsed, 1)
                violations.append(
                    f"Domain pacing violation: Domain '{domain}' was contacted {round(pacing_elapsed, 1)}s ago (minimum: {settings.DOMAIN_PACING_SECONDS}s, {remaining}s remaining)."
                )
                checks_passed["domain_pacing"] = False
            else:
                checks_passed["domain_pacing"] = True

            # ── 9. Circuit Breaker Check ──────────────────────────────────────
            cb_state = await self.circuit_breaker.evaluate_dynamic_state(db)
            cb_permits, cb_reason = self.circuit_breaker.permits_send(cb_state)
            if not cb_permits:
                violations.append(f"Circuit breaker violation: {cb_reason} (state: {cb_state.value}).")
                checks_passed["circuit_breaker"] = False
            else:
                checks_passed["circuit_breaker"] = True

            # ── 10. Gmail Account & Health ────────────────────────────────────
            gmail_ok, gmail_err = await self.check_gmail_health(db)
            if not gmail_ok:
                violations.append(f"Gmail health check failure: {gmail_err}.")
                checks_passed["gmail_healthy"] = False
            else:
                checks_passed["gmail_healthy"] = True

        except Exception as exc:
            # ── 11. Fail Closed on Unhandled Error ────────────────────────────
            log.error("Safety controller internal exception — failing closed", error=str(exc))
            violations.append(f"Safety controller internal error (fail-closed): {str(exc)}")
            checks_passed["internal_integrity"] = False

        # ── 12. Final Evaluation & Audit Trail ────────────────────────────────
        allowed = len(violations) == 0
        blocked_reason = "; ".join(violations) if not allowed else None
        send_attempt_id = None

        if not allowed and record_blocked_attempt and target_draft:
            try:
                attempt = SendAttempt(
                    draft_id=target_draft.id,
                    lead_id=target_draft.lead_id,
                    recipient_email=target_draft.recipient_email,
                    attempted_at=now,
                    result=SendAttemptResult.BLOCKED,
                    failure_reason=blocked_reason,
                )
                db.add(attempt)
                await db.commit()
                await db.refresh(attempt)
                send_attempt_id = attempt.id
            except Exception as audit_err:
                log.error("Failed to persist blocked send attempt audit log", error=str(audit_err))

        log.info(
            "Outreach safety validation completed",
            draft_id=str(draft_id),
            allowed=allowed,
            violations_count=len(violations),
            circuit_breaker=cb_state.value,
        )

        return SafetyCheckResult(
            allowed=allowed,
            violations=violations,
            blocked_reason=blocked_reason,
            circuit_breaker_state=cb_state,
            checks_passed=checks_passed,
            send_attempt_id=send_attempt_id,
            daily_sends_count=daily_sends,
            new_leads_count=new_leads,
            pacing_elapsed_seconds=pacing_elapsed,
        )
