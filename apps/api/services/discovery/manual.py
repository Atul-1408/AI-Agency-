"""
Manual Entry Lead Discovery Provider.
Allows owner to directly input target businesses or domains for research.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.discovery.base import (
    DiscoveredLead,
    LeadDiscoveryProvider,
    normalize_domain,
)


class ManualEntryProvider(LeadDiscoveryProvider):
    """Provider for directly inputted business prospects."""

    def __init__(self, manual_items: Optional[List[Dict[str, Any]]] = None):
        self._manual_items = manual_items or []

    @property
    def provider_name(self) -> str:
        return "manual_entry"

    async def is_configured(self) -> bool:
        return True

    def add_item(
        self,
        company_name: str,
        website_url: Optional[str] = None,
        domain: Optional[str] = None,
        phone: Optional[str] = None,
        address: Optional[str] = None,
        industry: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> None:
        self._manual_items.append({
            "company_name": company_name,
            "website_url": website_url,
            "domain": domain,
            "phone": phone,
            "address": address,
            "industry": industry,
            "notes": notes,
        })

    async def discover(
        self,
        query: str,
        location: Optional[str] = None,
        limit: int = 20,
    ) -> List[DiscoveredLead]:
        """Convert queued manual items into DiscoveredLead objects."""
        leads: List[DiscoveredLead] = []
        batch_limit = min(max(1, limit), 20)

        for item in self._manual_items[:batch_limit]:
            company_name = item.get("company_name", "").strip() or "Manual Prospect"
            website_url = item.get("website_url")
            raw_domain = item.get("domain") or (normalize_domain(website_url) if website_url else "")
            domain = normalize_domain(raw_domain) or f"manual-{company_name.lower().replace(' ', '-')[:25]}.local"

            lead = DiscoveredLead(
                company_name=company_name,
                domain=domain,
                website_url=website_url,
                phone=item.get("phone"),
                address=item.get("address"),
                industry=item.get("industry") or query,
                source_type=self.provider_name,
                source_query=f"manual:{query}" if query else "manual_entry",
                source_url=website_url,
                raw_data={"notes": item.get("notes")},
            )
            leads.append(lead)

        return leads
