"""
Lead Research Agent — Phase 2.
Coordinates business discovery, technical website audit, public contact extraction,
deterministic qualification scoring, and persistence.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from agents.base_agent import BaseAgent
from models import AgentRun, LeadStatus
from services.discovery import (
    DiscoveredLead,
    GooglePlacesProvider,
    ManualEntryProvider,
    get_discovery_provider,
)
from services.lead_service import LeadService
from tools import (
    PublicContactFinderTool,
    QualificationScorerTool,
    WebsiteAuditorTool,
)

log = structlog.get_logger(__name__)


class LeadResearchAgent(BaseAgent):
    """
    Lead Research Agent implementation.
    Gathers prospects via pluggable discovery providers, audits websites objectively,
    extracts public business contacts, and deterministically scores opportunities.
    """
    name: str = "lead_research"

    async def execute(
        self,
        db: AsyncSession,
        run: AgentRun,
        input_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        query = input_data.get("query", "").strip()
        location = input_data.get("location")
        provider_name = input_data.get("provider", "google_places")
        limit = min(max(1, int(input_data.get("limit", 20))), 20)
        manual_items = input_data.get("manual_items", [])

        self.log.info(
            "Executing lead research run",
            provider=provider_name,
            query=query,
            location=location,
            limit=limit,
        )

        # 1. Resolve Provider
        provider = get_discovery_provider(provider_name)
        if isinstance(provider, ManualEntryProvider) and manual_items:
            for item in manual_items:
                provider.add_item(**item)

        # 2. Discover Prospects
        discovered_leads: List[DiscoveredLead] = await provider.discover(
            query=query,
            location=location,
            limit=limit,
        )

        self.log.info("Prospects discovered", count=len(discovered_leads))

        # 3. Initialize Tools
        auditor = WebsiteAuditorTool(crawl_delay_seconds=1.0, timeout_seconds=8.0)
        contact_finder = PublicContactFinderTool()
        scorer = QualificationScorerTool()
        lead_service = LeadService(db)

        saved_leads = []
        qualified_count = 0
        disqualified_count = 0

        # 4. Research & Qualify Pipeline
        for prospect in discovered_leads:
            # Objective Technical Website Audit
            audit_result = await auditor.audit(prospect.website_url)

            # Public Contact Extraction
            contact_info = contact_finder.extract_from_html(
                html=audit_result.html_content or "",
                target_domain=prospect.domain,
            )
            # If discovery provider already provided a public business phone, retain it if not found on page
            if not contact_info.phone and prospect.phone:
                contact_info.phone = prospect.phone

            # Deterministic Qualification Scoring
            evaluation = scorer.evaluate(
                audit=audit_result,
                contact=contact_info,
                raw_data=prospect.raw_data,
            )

            # Deduplication & Persistence
            saved_lead, is_new = await lead_service.save_researched_lead(
                discovered=prospect,
                audit=audit_result,
                contact=contact_info,
                evaluation=evaluation,
            )

            if saved_lead.status == LeadStatus.QUALIFIED:
                qualified_count += 1
            elif saved_lead.status == LeadStatus.DISQUALIFIED:
                disqualified_count += 1

            saved_leads.append({
                "id": str(saved_lead.id),
                "company_name": saved_lead.company_name,
                "domain": saved_lead.domain,
                "score": saved_lead.qualification_score,
                "status": saved_lead.status.value,
                "is_new": is_new,
            })

        await db.commit()

        return {
            "query": query,
            "location": location,
            "provider": provider_name,
            "total_discovered": len(discovered_leads),
            "total_saved": len(saved_leads),
            "qualified_count": qualified_count,
            "disqualified_count": disqualified_count,
            "leads": saved_leads,
        }
