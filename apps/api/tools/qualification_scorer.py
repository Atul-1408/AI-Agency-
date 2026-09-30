"""
Qualification Scorer Tool.
Applies a strictly deterministic rubric to calculate opportunity score (0 to 100).
Zero subjective AI claims — scoring is tied 100% to observable technical facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from models import LeadStatus
from tools.website_auditor import AuditResult
from tools.contact_finder import ContactInfo


@dataclass
class QualificationEvaluation:
    """Outcome of deterministic lead qualification scoring."""
    score: int
    status: LeadStatus
    scoring_breakdown: List[Dict[str, Any]]
    qualification_notes: str


class QualificationScorerTool:
    """Deterministic opportunity scorer for web agency prospecting."""

    def evaluate(
        self,
        audit: AuditResult,
        contact: ContactInfo,
        raw_data: Optional[Dict[str, Any]] = None,
        is_suppressed: bool = False,
    ) -> QualificationEvaluation:
        """
        Evaluate objective technical factors and compute a deterministic score.
        Score range: 0 to 100.
        """
        if is_suppressed:
            return QualificationEvaluation(
                score=0,
                status=LeadStatus.DISQUALIFIED,
                scoring_breakdown=[{"factor": "Suppression List", "points": 0, "reason": "Domain/Phone is opted out"}],
                qualification_notes="Prospect is present on opt-out/suppression list.",
            )

        score = 0
        breakdown: List[Dict[str, Any]] = []

        # 1. Website Presence & Connectivity
        if not audit.has_website:
            score += 40
            breakdown.append({
                "factor": "No Website",
                "points": 40,
                "reason": "Business has no online website presence (highest redesign/build opportunity)",
            })
        elif audit.status_code and audit.status_code >= 400:
            score += 35
            breakdown.append({
                "factor": "Broken Website",
                "points": 35,
                "reason": f"Website returns HTTP error status {audit.status_code}",
            })
        else:
            # 2. Mobile Viewport / Responsiveness
            if audit.is_responsive is False:
                score += 25
                breakdown.append({
                    "factor": "Not Mobile Responsive",
                    "points": 25,
                    "reason": "Missing mobile viewport meta tag; poor mobile usability",
                })

            # 3. SSL / Security
            if audit.has_ssl is False:
                score += 15
                breakdown.append({
                    "factor": "Insecure Connection",
                    "points": 15,
                    "reason": "Site served over unencrypted HTTP (no valid SSL)",
                })

            # 4. Outdated Copyright
            if audit.copyright_year:
                current_year = datetime.now(timezone.utc).year
                age = current_year - audit.copyright_year
                if age >= 4:
                    score += 10
                    breakdown.append({
                        "factor": "Outdated Copyright",
                        "points": 10,
                        "reason": f"Copyright year is {audit.copyright_year} ({age} years old)",
                    })

            # 5. Performance / Latency
            if audit.load_time_ms and audit.load_time_ms > 2500:
                score += 10
                breakdown.append({
                    "factor": "Slow Response Time",
                    "points": 10,
                    "reason": f"TTFB load time of {audit.load_time_ms}ms exceeds 2500ms threshold",
                })

        # 6. Contact Reachability
        has_email = bool(contact.email)
        has_phone = bool(contact.phone)

        if has_email:
            score += 10
            breakdown.append({
                "factor": "Public Email Discovered",
                "points": 10,
                "reason": f"Public business email available ({contact.email_verification_status.value})",
            })

        if not has_email and not has_phone:
            score -= 30
            breakdown.append({
                "factor": "Missing Contact Points",
                "points": -30,
                "reason": "No public business email or phone number found",
            })

        # 7. Active Business Signals (e.g. Google Reviews)
        if raw_data:
            reviews_count = raw_data.get("user_ratings_total") or 0
            if isinstance(reviews_count, (int, float)) and reviews_count >= 20:
                score += 10
                breakdown.append({
                    "factor": "Active Business Traction",
                    "points": 10,
                    "reason": f"Active customer base with {int(reviews_count)} public reviews",
                })

        # 8. Negative Penalties: Modern Frameworks (Redesign unlikely)
        tech = audit.tech_stack or {}
        if tech.get("framework") in ("Next.js", "React"):
            score -= 50
            breakdown.append({
                "factor": "Modern Web Application",
                "points": -50,
                "reason": f"Website is already built with modern {tech.get('framework')} stack",
            })

        # Clamp score to 0..100
        final_score = max(0, min(100, score))

        # Assign status tier
        if final_score >= 60:
            status = LeadStatus.QUALIFIED
            notes = f"Qualified opportunity (Score: {final_score}/100). Technical issues identified with high outreach viability."
        elif final_score >= 30:
            status = LeadStatus.RESEARCHED
            notes = f"Moderate/low priority opportunity (Score: {final_score}/100)."
        else:
            status = LeadStatus.DISQUALIFIED
            notes = f"Disqualified (Score: {final_score}/100). Insufficient opportunity or lack of contact reachability."

        return QualificationEvaluation(
            score=final_score,
            status=status,
            scoring_breakdown=breakdown,
            qualification_notes=notes,
        )
