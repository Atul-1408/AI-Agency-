"""Discovery providers module."""
from services.discovery.base import (
    DiscoveredLead,
    LeadDiscoveryProvider,
    ProviderNotConfiguredError,
    normalize_domain,
)
from services.discovery.google_places import GooglePlacesProvider
from services.discovery.manual import ManualEntryProvider


def get_discovery_provider(name: str) -> LeadDiscoveryProvider:
    """Factory to retrieve a discovery provider by identifier."""
    clean_name = (name or "").lower().strip()
    if clean_name in ("google_places", "google", "places"):
        return GooglePlacesProvider()
    elif clean_name in ("manual_entry", "manual"):
        return ManualEntryProvider()
    else:
        raise ValueError(f"Unknown discovery provider '{name}'. Supported: google_places, manual_entry")


__all__ = [
    "DiscoveredLead",
    "LeadDiscoveryProvider",
    "ProviderNotConfiguredError",
    "GooglePlacesProvider",
    "ManualEntryProvider",
    "normalize_domain",
    "get_discovery_provider",
]
