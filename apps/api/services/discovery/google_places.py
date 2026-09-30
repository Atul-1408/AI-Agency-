"""
Google Places API Lead Discovery Provider.
Discovers local businesses, addresses, ratings, and websites.
Strictly reports unconfigured state if GOOGLE_PLACES_API_KEY is not present.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
import httpx
import structlog

from core.config import settings
from services.discovery.base import (
    DiscoveredLead,
    LeadDiscoveryProvider,
    ProviderNotConfiguredError,
    normalize_domain,
)

log = structlog.get_logger(__name__)


class GooglePlacesProvider(LeadDiscoveryProvider):
    """Discovery provider backed by official Google Places API."""

    @property
    def provider_name(self) -> str:
        return "google_places"

    async def is_configured(self) -> bool:
        """Check if Google Places API key is configured."""
        key = getattr(settings, "GOOGLE_PLACES_API_KEY", "")
        return bool(key and key.strip())

    async def discover(
        self,
        query: str,
        location: Optional[str] = None,
        limit: int = 20,
    ) -> List[DiscoveredLead]:
        """
        Search Google Places Text Search API.
        Capped at limit (max 20 per batch).
        """
        if not await self.is_configured():
            raise ProviderNotConfiguredError(
                "Google Places API key is not configured. "
                "Set GOOGLE_PLACES_API_KEY in your .env file or use Manual Entry."
            )

        batch_limit = min(max(1, limit), 20)
        api_key = settings.GOOGLE_PLACES_API_KEY
        search_term = f"{query} in {location}" if location else query

        leads: List[DiscoveredLead] = []

        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Search places
            search_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
            params = {
                "query": search_term,
                "key": api_key,
            }
            log.info("Querying Google Places API", query=search_term, limit=batch_limit)
            try:
                resp = await client.get(search_url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.error("Google Places search request failed", error=str(exc))
                raise RuntimeError(f"Google Places API request failed: {exc}") from exc

            status = data.get("status")
            if status not in ("OK", "ZERO_RESULTS"):
                err_msg = data.get("error_message", status)
                log.error("Google Places API error response", status=status, message=err_msg)
                raise RuntimeError(f"Google Places API error ({status}): {err_msg}")

            results = data.get("results", [])[:batch_limit]

            for place in results:
                place_id = place.get("place_id")
                company_name = place.get("name") or "Unknown Business"
                address = place.get("formatted_address")

                # 2. Fetch detailed place profile (website, phone)
                website_url = None
                phone = None
                maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else None

                if place_id:
                    details_url = "https://maps.googleapis.com/maps/api/place/details/json"
                    details_params = {
                        "place_id": place_id,
                        "fields": "website,formatted_phone_number,url,rating,user_ratings_total",
                        "key": api_key,
                    }
                    try:
                        det_resp = await client.get(details_url, params=details_params)
                        if det_resp.status_code == 200:
                            det_data = det_resp.json().get("result", {})
                            website_url = det_data.get("website")
                            phone = det_data.get("formatted_phone_number")
                            if det_data.get("url"):
                                maps_url = det_data.get("url")
                    except Exception as e:
                        log.warning("Could not fetch place details", place_id=place_id, error=str(e))

                domain = normalize_domain(website_url) if website_url else ""
                if not domain:
                    # Deterministic canonical domain placeholder for prospects without website
                    clean_slug = re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")
                    domain = f"no-website-{clean_slug[:30]}-{place_id or 'unknown'}.local"

                lead = DiscoveredLead(
                    company_name=company_name,
                    domain=domain,
                    website_url=website_url,
                    phone=phone,
                    address=address,
                    industry=query,
                    source_type=self.provider_name,
                    source_query=search_term,
                    source_url=maps_url,
                    raw_data={
                        "place_id": place_id,
                        "rating": place.get("rating"),
                        "user_ratings_total": place.get("user_ratings_total"),
                        "business_status": place.get("business_status"),
                    },
                )
                leads.append(lead)

        return leads
