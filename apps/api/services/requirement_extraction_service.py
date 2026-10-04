"""
Phase 5 Stage 5.2 — Client Requirement Extraction & Intelligence Service.

Responsibilities:
1. Deterministic requirement extraction from normalized conversation messages.
2. Evidence tracing: every requirement links to a specific message, direction, and excerpt.
3. Conflict resolution & versioning: latest client statement becomes active requirement;
   all historical versions and evidence are preserved.
4. Missing data & clarification question generation.
5. Deterministic completeness assessment across 8 standard categories.
6. AI / Nemotron provider abstraction with strict untrusted-content boundaries.
7. Idempotent execution (running multiple times will not duplicate evidence or corrupt history).
8. Audit logging without sensitive credential or body leaks.

SECURITY GUARANTEES:
- Client messages are UNTRUSTED EXTERNAL DATA.
- Never execute instructions found in client messages (e.g. "Ignore previous instructions").
- Never fetch URLs found in client messages (prevents SSRF).
- Zero tokens or credentials in prompts or logs.
"""
from __future__ import annotations

import abc
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from models import AgentRun, AgentRunStatus
from models.client_intelligence import (
    ClarificationStatus,
    ClientClarification,
    ClientConversation,
    ClientConversationMessage,
    ClientConversationStatus,
    ClientRequirement,
    ClientRequirementEvidence,
    ClientRequirementVersion,
    MessageDirection,
    RequirementConfidence,
    RequirementStatus,
)

log = structlog.get_logger(__name__)


# ── Category & Key Definitions ────────────────────────────────────────────────

CATEGORY_GROUPS: Dict[str, List[str]] = {
    "CORE_BUSINESS": [
        "business_name",
        "business_type",
        "target_audience",
        "services",
        "products",
        "website_required",
        "website_type",
    ],
    "CONTENT": [
        "pages",
        "existing_website",
        "competitor_websites",
        "references",
    ],
    "DESIGN": [
        "design_preferences",
        "brand_preferences",
        "colors",
        "typography",
    ],
    "FUNCTIONALITY": [
        "features",
        "functionality",
        "integrations",
        "booking_requirements",
        "payment_requirements",
    ],
    "CONTACT": [
        "contact_information",
        "preferred_contact_method",
        "social_links",
        "location",
    ],
    "TECHNICAL": [
        "domain_requirements",
        "hosting_requirements",
    ],
    "TIMELINE": [
        "deadline",
    ],
    "BUDGET": [
        "budget",
    ],
}

# Critical fields for clarification generation if missing
CRITICAL_REQUIREMENTS: Dict[str, Tuple[str, str, str]] = {
    # key: (category_group, question, rationale)
    "business_type": (
        "CORE_BUSINESS",
        "What type of business or organization do you run?",
        "Essential to understand your industry and structure appropriate site architecture.",
    ),
    "services": (
        "CORE_BUSINESS",
        "What core services or products would you like highlighted on the website?",
        "Needed to design dedicated service pages and showcase your offerings clearly.",
    ),
    "pages": (
        "CONTENT",
        "What specific pages would you like on your website (e.g. Home, About, Services, Contact)?",
        "Required to plan site hierarchy, navigation flow, and content layout.",
    ),
    "functionality": (
        "FUNCTIONALITY",
        "Do you require special functionality such as online booking, contact forms, or payments?",
        "Determines technical requirements, third-party integrations, and UI components.",
    ),
    "design_preferences": (
        "DESIGN",
        "Do you have any design style preferences or colors in mind (e.g., minimalist, modern, dark)?",
        "Guides aesthetic selection, typography, color palette, and visual identity.",
    ),
    "budget": (
        "BUDGET",
        "Do you have a specific budget range in mind for this website?",
        "Helps tailor scope, feature recommendations, and implementation tiers.",
    ),
    "deadline": (
        "TIMELINE",
        "Do you have a target launch date or deadline for the project?",
        "Crucial for project milestone scheduling and sprint planning.",
    ),
}

# Reverse lookup: key -> category_group
KEY_TO_CATEGORY: Dict[str, str] = {
    key: group for group, keys in CATEGORY_GROUPS.items() for key in keys
}


# ── AI Provider Interface (Boundary) ──────────────────────────────────────────

class RequirementExtractionAIProvider(abc.ABC):
    """Abstract interface for optional AI/Nemotron extraction layer."""

    @abc.abstractmethod
    async def refine_requirements(
        self,
        conversation_context: str,
        current_requirements: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Refine or augment extracted requirements using AI.
        Must fail open/safely if provider is unconfigured or returns invalid data.
        """
        pass


class DefaultNemotronExtractionProvider(RequirementExtractionAIProvider):
    """
    Default Nemotron extraction provider.
    Fails safely without breaking deterministic pipeline if unconfigured.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    async def refine_requirements(
        self,
        conversation_context: str,
        current_requirements: Dict[str, Any],
    ) -> Dict[str, Any]:
        # If no active AI key or configuration, return current without mutation
        if not self.api_key or not self.api_key.strip():
            return {}
        # In this phase, deterministic extraction handles all core rules.
        # AI refinement will plug in when provider credentials are confirmed.
        return {}


# ── Extractor Class ───────────────────────────────────────────────────────────

class RequirementExtractionService:
    """
    Core service for extracting and managing client requirements from conversation messages.
    """

    def __init__(self, ai_provider: Optional[RequirementExtractionAIProvider] = None):
        self._ai_provider = ai_provider or DefaultNemotronExtractionProvider()

    # ── Deterministic Extraction Engine ───────────────────────────────────────

    def extract_from_message(
        self, message_text: str
    ) -> Dict[str, Tuple[Any, RequirementConfidence, str]]:
        """
        Extract requirements deterministically from a single message.

        Returns a dictionary:
            key -> (extracted_value, confidence, excerpt)

        SECURITY:
        All input text is treated strictly as data. Instructions inside message_text
        have zero effect on execution.
        """
        results: Dict[str, Tuple[Any, RequirementConfidence, str]] = {}
        if not message_text or not message_text.strip():
            return results

        text = message_text.strip()

        # 1. Business Name
        bn_match = re.search(
            r"(?:my|our)\s+(?:company|business|brand|clinic|firm|agency|store|shop)\s+(?:is|called|named)?\s*[:\-]?\s*[\"']?([A-Za-z0-9\s&.,'-]{3,40}?)[\"']?(?:[.,\n]|\s+and|\s+based|$)",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"(?:we are|i am with|we're at)\s+[\"']?([A-Za-z0-9\s&.,'-]{3,40}?)[\"']?(?:[.,\n]|\s+based|$)",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"(?:company|business)\s+name\s*[:\-]\s*[\"']?([A-Za-z0-9\s&.,'-]{3,40}?)[\"']?(?:[.,\n]|$)",
            text,
            re.IGNORECASE,
        )
        if bn_match:
            name = bn_match.group(1).strip()
            # filter out non-names like "looking for"
            if not any(stop in name.lower() for stop in ["looking", "interested", "hoping", "ready", "trying"]):
                results["business_name"] = (name, RequirementConfidence.HIGH, bn_match.group(0).strip())

        # 2. Business Type
        types_map = [
            (r"\b(?:dental\s+clinic|dentist|dental\s+practice)\b", "Dental Clinic"),
            (r"\b(?:law\s+firm|legal\s+practice|lawyer|attorney)\b", "Law Firm"),
            (r"\b(?:real\s+estate|realtor|realty|property\s+management)\b", "Real Estate Agency"),
            (r"\b(?:accounting\s+firm|accountant|cpa|bookkeeping)\b", "Accounting Firm"),
            (r"\b(?:restaurant|cafe|bistro|eatery|dining)\b", "Restaurant"),
            (r"\b(?:gym|fitness\s+center|personal\s+training|crossfit)\b", "Fitness & Gym"),
            (r"\b(?:plumbing|plumber)\b", "Plumbing Services"),
            (r"\b(?:roofing|roofer)\b", "Roofing Services"),
            (r"\b(?:construction|general\s+contractor|builder)\b", "Construction"),
            (r"\b(?:e-commerce|ecommerce|online\s+store|retail\s+shop)\b", "E-commerce Store"),
            (r"\b(?:consulting|consultancy|advisory)\b", "Consulting Agency"),
            (r"\b(?:saas|software\s+company|tech\s+startup)\b", "SaaS / Tech Startup"),
            (r"\b(?:clinic|medical\s+center|healthcare|doctor)\b", "Medical Clinic"),
            (r"\b(?:photography|photographer|photo\s+studio)\b", "Photography Studio"),
            (r"\b(?:hair\s+salon|beauty\s+salon|barbershop|spa)\b", "Salon & Spa"),
        ]
        for pattern, b_type in types_map:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                # Capture the sentence containing this match for evidence
                excerpt = self._extract_sentence(text, m.start())
                results["business_type"] = (b_type, RequirementConfidence.HIGH, excerpt)
                break

        # 3. Website Required & Type
        if re.search(r"\b(?:need\s+a\s+website|want\s+a\s+website|new\s+website|build\s+a\s+website|redesign\s+our\s+website|revamp\s+our\s+website)\b", text, re.IGNORECASE):
            m = re.search(r"\b(?:need\s+a\s+website|want\s+a\s+website|new\s+website|build\s+a\s+website|redesign\s+our\s+website|revamp\s+our\s+website)\b", text, re.IGNORECASE)
            excerpt = self._extract_sentence(text, m.start())
            results["website_required"] = (True, RequirementConfidence.HIGH, excerpt)

            if re.search(r"\b(?:e-commerce|online\s+store|sell\s+products)\b", text, re.IGNORECASE):
                results["website_type"] = ("E-commerce", RequirementConfidence.HIGH, excerpt)
            elif re.search(r"\b(?:landing\s+page|single\s+page|one\s+page)\b", text, re.IGNORECASE):
                results["website_type"] = ("Landing Page", RequirementConfidence.HIGH, excerpt)
            elif re.search(r"\b(?:portfolio)\b", text, re.IGNORECASE):
                results["website_type"] = ("Portfolio", RequirementConfidence.HIGH, excerpt)
            elif re.search(r"\b(?:booking|appointment)\b", text, re.IGNORECASE):
                results["website_type"] = ("Booking / Service Site", RequirementConfidence.HIGH, excerpt)
            else:
                results["website_type"] = ("Business Website", RequirementConfidence.MEDIUM, excerpt)

        # 4. Location
        loc_match = re.search(
            r"(?:located\s+in|based\s+in|office\s+in|headquartered\s+in|clinic\s+in)\s+([A-Za-z\s,.-]{2,35}?)(?:[.,\n]|\s+and|\s+serving|$)",
            text,
            re.IGNORECASE,
        )
        if loc_match:
            loc = loc_match.group(1).strip()
            if not any(stop in loc.lower() for stop in ["need", "want", "hope", "ready"]):
                results["location"] = (loc, RequirementConfidence.HIGH, loc_match.group(0).strip())

        # 5. Services
        srv_match = re.search(
            r"(?:our\s+services\s+(?:include|are)|services\s+we\s+offer|we\s+offer|we\s+provide|services\s*[:\-])\s*([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        if srv_match:
            raw_services = srv_match.group(1).strip()
            # Split comma, bullet, or 'and'
            services = [s.strip(" -•*") for s in re.split(r",|\band\b|;", raw_services) if len(s.strip(" -•*")) > 2]
            if services:
                results["services"] = (services, RequirementConfidence.HIGH, srv_match.group(0).strip())

        # 6. Pages
        pages_match = re.search(
            r"(?:pages?\s+(?:needed|required|we\s+need|wanted)?\s*[:\-]?\s*)([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        if pages_match:
            raw_pages = pages_match.group(1).strip()
            pages = [p.strip(" -•*") for p in re.split(r",|\band\b|;", raw_pages) if len(p.strip(" -•*")) > 2]
            if pages:
                results["pages"] = (pages, RequirementConfidence.HIGH, pages_match.group(0).strip())
        else:
            # Check for keyword mentions of common pages
            found_pages = []
            for p_name in ["Home", "About Us", "Services", "Contact", "Gallery", "Pricing", "FAQ", "Testimonials", "Blog"]:
                if re.search(rf"\b{p_name}\b", text, re.IGNORECASE):
                    found_pages.append(p_name)
            if len(found_pages) >= 2:
                results["pages"] = (found_pages, RequirementConfidence.MEDIUM, f"Mentioned pages: {', '.join(found_pages)}")

        # 7. Functionality / Features
        found_features = []
        if re.search(r"\b(?:contact\s+form|inquiry\s+form)\b", text, re.IGNORECASE):
            found_features.append("Contact Form")
        if re.search(r"\b(?:online\s+booking|appointment\s+scheduling|book\s+an?\s+appointment|calendly)\b", text, re.IGNORECASE):
            found_features.append("Online Booking")
            m = re.search(r"\b(?:online\s+booking|appointment\s+scheduling|book\s+an?\s+appointment|calendly)\b", text, re.IGNORECASE)
            results["booking_requirements"] = ("Online appointment scheduling", RequirementConfidence.HIGH, self._extract_sentence(text, m.start()))
        if re.search(r"\b(?:stripe|paypal|accept\s+payments|payment\s+gateway|credit\s+card\s+processing)\b", text, re.IGNORECASE):
            found_features.append("Payment Gateway")
            m = re.search(r"\b(?:stripe|paypal|accept\s+payments|payment\s+gateway|credit\s+card\s+processing)\b", text, re.IGNORECASE)
            results["payment_requirements"] = ("Online payment integration", RequirementConfidence.HIGH, self._extract_sentence(text, m.start()))
        if re.search(r"\b(?:chat\s+widget|live\s+chat|whatsapp\s+button)\b", text, re.IGNORECASE):
            found_features.append("Live Chat Widget")
        if re.search(r"\b(?:newsletter\s+signup|email\s+list)\b", text, re.IGNORECASE):
            found_features.append("Newsletter Signup")
        if re.search(r"\b(?:google\s+maps|location\s+map)\b", text, re.IGNORECASE):
            found_features.append("Google Maps Integration")
        if re.search(r"\b(?:user\s+login|customer\s+portal|membership)\b", text, re.IGNORECASE):
            found_features.append("User Portal / Login")

        if found_features:
            results["features"] = (found_features, RequirementConfidence.HIGH, f"Features: {', '.join(found_features)}")
            results["functionality"] = (found_features, RequirementConfidence.HIGH, f"Functionality: {', '.join(found_features)}")

        # 8. Design Preferences & Colors (evaluated independently)
        design_match = re.search(
            r"\b(clean\s+and\s+modern|minimalist|dark\s+theme|dark\s+mode|light\s+and\s+minimal|black\s+and\s+gold|blue\s+and\s+white|luxury|vibrant|professional|retro)\b",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"(?:design\s+(?:preferences?|style)|look\s+and\s+feel)\s*(?:is|should\s+be)?\s*[:\-]?\s*([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        if design_match:
            d_val = design_match.group(1).strip()
            results["design_preferences"] = (d_val, RequirementConfidence.HIGH, self._extract_sentence(text, design_match.start()))

        colors_match = re.search(
            r"(?:colors?|color\s+palette|color\s+scheme)\s*(?:is|are|should\s+be)?\s*[:\-]?\s*([^.\n]+)",
            text,
            re.IGNORECASE,
        )
        if colors_match:
            c_val = colors_match.group(1).strip()
            results["colors"] = (c_val, RequirementConfidence.HIGH, colors_match.group(0).strip())
        elif re.search(r"\b(?:dark\s+theme|dark\s+mode|dark\s+website|light\s+and\s+minimal|black\s+and\s+gold|blue\s+and\s+white)\b", text, re.IGNORECASE):
            m = re.search(r"\b(?:dark\s+theme|dark\s+mode|dark\s+website|light\s+and\s+minimal|black\s+and\s+gold|blue\s+and\s+white)\b", text, re.IGNORECASE)
            val = m.group(0).strip()
            excerpt = self._extract_sentence(text, m.start())
            if "dark" in val.lower():
                results["colors"] = ("Dark Theme", RequirementConfidence.MEDIUM, excerpt)
            elif "light" in val.lower():
                results["colors"] = ("Light & Minimal", RequirementConfidence.MEDIUM, excerpt)
            elif "blue" in val.lower():
                results["colors"] = ("Blue & White", RequirementConfidence.MEDIUM, excerpt)
            elif "gold" in val.lower():
                results["colors"] = ("Black & Gold", RequirementConfidence.MEDIUM, excerpt)

        # 9. Budget
        budget_match = re.search(
            r"(?:budget\s*(?:is|around|of)?\s*[:\-]?\s*)([$€£₹]?\s*[0-9,]+(?:\s*-\s*[$€£₹]?\s*[0-9,]+)?|\b[0-9,]+\s*(?:USD|EUR|GBP|INR|dollars)\b)",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"([$€£₹]\s*[0-9,]+(?:\s*-\s*[$€£₹]?\s*[0-9,]+)?|\b[0-9,]+\s*(?:USD|EUR|GBP|INR|dollars)\b)",
            text,
            re.IGNORECASE,
        )
        if budget_match:
            b_val = budget_match.group(1).strip()
            results["budget"] = (b_val, RequirementConfidence.HIGH, budget_match.group(0).strip())

        # 10. Deadline
        deadline_match = re.search(
            r"(?:deadline|launch\s+by|need\s+it\s+by|target\s+launch|launch\s+date|needed\s+by|launch\s+in)\s*[:\-]?\s*([^.\n]+)",
            text,
            re.IGNORECASE,
        ) or re.search(
            r"\b(asap|next\s+month|in\s+\d+\s+weeks?|by\s+end\s+of\s+(?:the\s+month|year|[A-Za-z]+))\b",
            text,
            re.IGNORECASE,
        )
        if deadline_match:
            d_val = deadline_match.group(1).strip()
            results["deadline"] = (d_val, RequirementConfidence.HIGH, deadline_match.group(0).strip())

        # 11. Contact Info & Preferred Contact Method
        phone_match = re.search(r"\b(?:\+?\d{1,2}\s*)?(?:\(\d{3}\)|\d{3})[-.\s]?\d{3}[-.\s]?\d{4}\b", text)
        if phone_match:
            results["contact_information"] = (phone_match.group(0).strip(), RequirementConfidence.HIGH, phone_match.group(0).strip())

        if re.search(r"\b(?:reach\s+me\s+by|reach\s+us\s+by|preferred\s+contact)\s*(?:email|phone|whatsapp)\b", text, re.IGNORECASE):
            m = re.search(r"\b(?:reach\s+me\s+by|reach\s+us\s+by|preferred\s+contact)\s*(?:email|phone|whatsapp)\b", text, re.IGNORECASE)
            results["preferred_contact_method"] = (m.group(0).strip(), RequirementConfidence.HIGH, m.group(0).strip())

        # 12. References & Existing Website
        ref_match = re.search(
            r"(?:existing\s+website|current\s+website|current\s+site)\s*(?:is)?\s*[:\-]?\s*([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)",
            text,
            re.IGNORECASE,
        )
        if ref_match:
            results["existing_website"] = (ref_match.group(1).strip(), RequirementConfidence.HIGH, ref_match.group(0).strip())

        comp_match = re.search(
            r"(?:competitor|similar\s+to|like\s+the\s+site|inspiration\s+from)\s*[:\-]?\s*([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)",
            text,
            re.IGNORECASE,
        )
        if comp_match:
            results["competitor_websites"] = ([comp_match.group(1).strip()], RequirementConfidence.HIGH, comp_match.group(0).strip())

        return results

    def _extract_sentence(self, text: str, pos: int) -> str:
        """Extract a short sentence/window around a character position for concise evidence."""
        start = max(0, text.rfind(".", 0, pos) + 1)
        end = text.find(".", pos)
        if end == -1:
            end = len(text)
        excerpt = text[start:end].strip()
        # Cap excerpt at 250 characters
        if len(excerpt) > 250:
            excerpt = excerpt[:247] + "..."
        return excerpt or text[pos:min(len(text), pos + 100)]

    # ── Completeness Assessment ───────────────────────────────────────────────

    def evaluate_completeness(
        self, requirements_dict: Dict[str, ClientRequirement]
    ) -> Dict[str, Any]:
        """
        Compute deterministic completeness assessment across the 8 standard categories.
        """
        categories_result = []
        total_fields_all = 0
        total_present_all = 0

        for cat_name, fields in CATEGORY_GROUPS.items():
            total_fields = len(fields)
            present = []
            missing = []

            for field in fields:
                req = requirements_dict.get(field)
                if req and req.value is not None and req.status != RequirementStatus.UNKNOWN:
                    present.append(field)
                else:
                    missing.append(field)

            pct = round((len(present) / total_fields) * 100.0, 1) if total_fields else 0.0
            cat_status = "complete" if pct >= 100.0 else ("partial" if pct > 0.0 else "empty")

            categories_result.append({
                "category": cat_name,
                "status": cat_status,
                "total_fields": total_fields,
                "present_fields": present,
                "missing_fields": missing,
                "completeness_percentage": pct,
            })

            total_fields_all += total_fields
            total_present_all += len(present)

        overall_pct = (
            round((total_present_all / total_fields_all) * 100.0, 1)
            if total_fields_all
            else 0.0
        )
        overall_status = "complete" if overall_pct >= 100.0 else ("partial" if overall_pct > 0.0 else "empty")

        return {
            "overall_completeness_percentage": overall_pct,
            "overall_status": overall_status,
            "categories": categories_result,
            "total_fields": total_fields_all,
            "total_present": total_present_all,
            "total_missing": total_fields_all - total_present_all,
        }

    # ── Extraction Orchestration ──────────────────────────────────────────────

    async def extract_and_store_requirements(
        self,
        conversation_id: uuid.UUID,
        owner_email: str,
        db: AsyncSession,
    ) -> Tuple[List[ClientRequirement], List[ClientClarification], Dict[str, Any]]:
        """
        Main execution:
        1. Verifies conversation and owner access.
        2. Loads all messages ordered chronologically (position asc).
        3. Deterministically extracts requirements per message.
        4. Handles conflict resolution and versioning:
           - Latest explicit client statement wins.
           - Historical versions and evidence are preserved.
        5. Generates structured clarifications for missing critical requirements.
        6. Updates conversation state (status=REQUIREMENTS_READY, intent, signals).
        7. Records audit log.
        """
        # 1. Load conversation
        conv = (await db.scalars(
            select(ClientConversation).where(
                ClientConversation.id == conversation_id,
                ClientConversation.owner_email == owner_email,
            )
        )).first()

        if conv is None:
            raise ValueError(f"Conversation '{conversation_id}' not found or access denied.")

        # 2. Load messages in ascending order
        messages = (await db.scalars(
            select(ClientConversationMessage)
            .where(ClientConversationMessage.conversation_id == conversation_id)
            .order_by(ClientConversationMessage.position.asc())
        )).all()

        # 3. Load existing requirements map (key -> ClientRequirement)
        existing_reqs_list = (await db.scalars(
            select(ClientRequirement).where(
                ClientRequirement.conversation_id == conversation_id
            )
        )).all()
        reqs_map: Dict[str, ClientRequirement] = {r.key: r for r in existing_reqs_list}

        # 4. Extract chronologically across messages
        for msg in messages:
            if not msg.body_text:
                continue

            extracted = self.extract_from_message(msg.body_text)

            for key, (val, confidence, excerpt) in extracted.items():
                cat_group = KEY_TO_CATEGORY.get(key, "CORE_BUSINESS")

                if key not in reqs_map:
                    # New requirement identified
                    req = ClientRequirement(
                        conversation_id=conversation_id,
                        owner_email=owner_email,
                        key=key,
                        category_group=cat_group,
                        value=val,
                        status=RequirementStatus.IDENTIFIED,
                        confidence=confidence,
                        current_version=1,
                    )
                    db.add(req)
                    await db.flush()
                    await db.refresh(req)

                    # Initial version
                    ver = ClientRequirementVersion(
                        requirement_id=req.id,
                        version_number=1,
                        old_value=None,
                        new_value=val,
                        change_reason="Initial extraction from conversation message",
                        source_message_id=msg.id,
                    )
                    db.add(ver)

                    # Initial evidence
                    ev = ClientRequirementEvidence(
                        requirement_id=req.id,
                        conversation_message_id=msg.id,
                        source_message_direction=msg.direction,
                        excerpt=excerpt,
                        extraction_method="deterministic",
                        confidence=confidence,
                    )
                    db.add(ev)
                    await db.flush()

                    reqs_map[key] = req

                else:
                    # Existing requirement: check for change / conflict resolution
                    existing = reqs_map[key]

                    # Check if value actually changed
                    if existing.value != val:
                        old_val = existing.value
                        new_version_num = existing.current_version + 1

                        # Update existing requirement with latest statement
                        existing.value = val
                        existing.confidence = confidence
                        existing.status = RequirementStatus.IDENTIFIED
                        existing.current_version = new_version_num
                        existing.updated_at = datetime.now(timezone.utc)

                        # Record version transition
                        ver = ClientRequirementVersion(
                            requirement_id=existing.id,
                            version_number=new_version_num,
                            old_value=old_val,
                            new_value=val,
                            change_reason=f"Updated by client statement in message position {msg.position}",
                            source_message_id=msg.id,
                        )
                        db.add(ver)

                    # Add evidence if not already present for this message & excerpt
                    existing_ev = (await db.scalars(
                        select(ClientRequirementEvidence).where(
                            ClientRequirementEvidence.requirement_id == existing.id,
                            ClientRequirementEvidence.conversation_message_id == msg.id,
                            ClientRequirementEvidence.excerpt == excerpt,
                        )
                    )).first()

                    if existing_ev is None:
                        ev = ClientRequirementEvidence(
                            requirement_id=existing.id,
                            conversation_message_id=msg.id,
                            source_message_direction=msg.direction,
                            excerpt=excerpt,
                            extraction_method="deterministic",
                            confidence=confidence,
                        )
                        db.add(ev)
                        await db.flush()

        # 5. Missing Data & Clarification Generation
        clarifications_list: List[ClientClarification] = []
        for crit_key, (grp, q_text, r_text) in CRITICAL_REQUIREMENTS.items():
            req_item = reqs_map.get(crit_key)
            has_value = req_item is not None and req_item.value is not None

            # Look for existing clarification for this key
            existing_clar = (await db.scalars(
                select(ClientClarification).where(
                    ClientClarification.conversation_id == conversation_id,
                    ClientClarification.requirement_key == crit_key,
                )
            )).first()

            if not has_value:
                # Still missing -> ensure pending clarification exists
                if existing_clar is None:
                    new_clar = ClientClarification(
                        conversation_id=conversation_id,
                        owner_email=owner_email,
                        category_group=grp,
                        requirement_key=crit_key,
                        question=q_text,
                        rationale=r_text,
                        status=ClarificationStatus.PENDING,
                    )
                    db.add(new_clar)
                    clarifications_list.append(new_clar)
                else:
                    clarifications_list.append(existing_clar)
            else:
                # Answered/identified -> update clarification if pending
                if existing_clar is not None:
                    if existing_clar.status == ClarificationStatus.PENDING:
                        existing_clar.status = ClarificationStatus.ANSWERED
                    clarifications_list.append(existing_clar)

        await db.flush()

        # 6. Update conversation signals & state
        conv.status = ClientConversationStatus.REQUIREMENTS_READY

        if "business_type" in reqs_map and reqs_map["business_type"].value:
            conv.intent = f"Build website for {reqs_map['business_type'].value}"
        elif "website_required" in reqs_map:
            conv.intent = "Build new website"

        if "budget" in reqs_map and reqs_map["budget"].value:
            conv.budget_signal = str(reqs_map["budget"].value)

        if "deadline" in reqs_map and reqs_map["deadline"].value:
            conv.timeline_signal = str(reqs_map["deadline"].value)

        await db.flush()
        await db.refresh(conv)

        # 7. Evaluate completeness
        completeness = self.evaluate_completeness(reqs_map)

        # 8. Record audit log
        run = AgentRun(
            agent_name="client_requirement_extraction_service",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "event": "conversation_requirements_extracted",
                "conversation_id": str(conversation_id),
                "owner": owner_email,
                "message_count": len(messages),
                "requirements_count": len(reqs_map),
                "completeness_percentage": completeness["overall_completeness_percentage"],
            },
            output_data={
                "result": "ok",
                "requirements_count": len(reqs_map),
                "clarifications_count": len(clarifications_list),
            },
        )
        db.add(run)
        await db.flush()

        log.info(
            "Requirements extracted for conversation",
            conversation_id=str(conversation_id),
            requirements_count=len(reqs_map),
            clarifications_count=len(clarifications_list),
            completeness=completeness["overall_completeness_percentage"],
        )

        all_reqs = list(reqs_map.values())
        return all_reqs, clarifications_list, completeness
