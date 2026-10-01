"""
Lead Discovery Provider abstraction.
Allows business prospect discovery to be provider-agnostic.
New providers (e.g. Yelp, OpenStreetMap, Crunchbase) can be added without modifying the agent.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import urllib.parse


class ProviderNotConfiguredError(Exception):
    """Raised when an external discovery provider lacks necessary credentials."""
    pass


@dataclass
class DiscoveredLead:
    """Standardized representation of a business prospect discovered by any provider."""
    company_name: str
    domain: str
    website_url: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    industry: Optional[str] = None
    source_type: str = "unknown"
    source_query: Optional[str] = None
    source_url: Optional[str] = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_data: Dict[str, Any] = field(default_factory=dict)


def normalize_domain(url_or_domain: str) -> str:
    """
    Extract and clean canonical domain name from a URL or raw string.
    Example: 'https://www.Example.com/contact?ref=1' -> 'example.com'
    """
    raw = (url_or_domain or "").strip().lower()
    if not raw:
        return ""
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raw = "http://" + raw
    try:
        parsed = urllib.parse.urlparse(raw)
        host = parsed.hostname or parsed.netloc or raw
        if host.startswith("www."):
            host = host[4:]
        # Remove any trailing port or dots
        host = host.split(":")[0].strip(".")
        return host
    except Exception:
        return raw.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]


class LeadDiscoveryProvider(ABC):
    """Abstract base provider for business prospect discovery."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifier name of this provider."""
        ...

    @abstractmethod
    async def is_configured(self) -> bool:
        """Return True if credentials and environment are ready."""
        ...

    @abstractmethod
    async def discover(
        self,
        query: str,
        location: Optional[str] = None,
        limit: int = 20,
    ) -> List[DiscoveredLead]:
        """
        Discover business prospects based on query and optional location.
        Maximum limit is capped at 20 per batch.
        """
        ...
