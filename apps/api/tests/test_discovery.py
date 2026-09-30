"""
Tests for lead discovery provider abstraction, normalization, and providers.
"""
from __future__ import annotations

import pytest

from services.discovery import (
    GooglePlacesProvider,
    ManualEntryProvider,
    ProviderNotConfiguredError,
    get_discovery_provider,
    normalize_domain,
)


def test_normalize_domain_various_formats():
    """Verify domain normalization strips protocols, paths, ports, and www."""
    assert normalize_domain("https://www.Example.COM/contact?ref=1") == "example.com"
    assert normalize_domain("http://sub.domain.co.uk:8080/page") == "sub.domain.co.uk"
    assert normalize_domain("www.my-plumbing-co.com/") == "my-plumbing-co.com"
    assert normalize_domain("invalid-domain") == "invalid-domain"
    assert normalize_domain("") == ""


def test_get_discovery_provider_factory():
    """Factory returns correct provider instances."""
    places = get_discovery_provider("google_places")
    assert isinstance(places, GooglePlacesProvider)
    manual = get_discovery_provider("manual_entry")
    assert isinstance(manual, ManualEntryProvider)

    with pytest.raises(ValueError, match="Unknown discovery provider"):
        get_discovery_provider("unsupported_provider")


@pytest.mark.asyncio
async def test_google_places_unconfigured_raises():
    """GooglePlacesProvider raises ProviderNotConfiguredError if API key missing."""
    provider = GooglePlacesProvider()
    # In test environment, GOOGLE_PLACES_API_KEY is not set
    assert await provider.is_configured() is False
    with pytest.raises(ProviderNotConfiguredError, match="Google Places API key is not configured"):
        await provider.discover("plumbers", "Austin, TX")


@pytest.mark.asyncio
async def test_manual_entry_provider():
    """ManualEntryProvider formats and yields discovered leads with provenance."""
    provider = ManualEntryProvider()
    provider.add_item(
        company_name="Austin Roofing Pros",
        website_url="https://www.austinroofingpros.com",
        phone="(512) 555-1234",
        address="100 Congress Ave, Austin, TX",
        industry="Roofing",
    )

    leads = await provider.discover(query="Roofing", location="Austin, TX", limit=10)
    assert len(leads) == 1
    lead = leads[0]
    assert lead.company_name == "Austin Roofing Pros"
    assert lead.domain == "austinroofingpros.com"
    assert lead.phone == "(512) 555-1234"
    assert lead.source_type == "manual_entry"
    assert lead.source_query == "manual:Roofing"
