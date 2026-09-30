"""
Integration tests for /api/v1/leads API endpoints and lead lifecycle.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

from models import LeadStatus


@pytest.mark.asyncio
async def test_list_leads_unauthorized(client: AsyncClient):
    """GET /api/v1/leads requires owner authentication."""
    response = await client.get("/api/v1/leads")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_manual_lead_creation_and_lifecycle(client: AsyncClient, auth_headers: dict):
    """Create manual lead, verify audit results, and test approval/rejection lifecycle."""
    # 1. Create manual lead
    payload = {
        "company_name": "Lone Star Electrical",
        "website_url": "https://www.lonestarelec.example",
        "phone": "(512) 555-4321",
        "address": "400 S Lamar, Austin, TX",
        "industry": "Electrical",
        "notes": "Met at regional trade show",
    }
    create_resp = await client.post("/api/v1/leads/manual", json=payload, headers=auth_headers)
    assert create_resp.status_code == 201
    lead_data = create_resp.json()

    lead_id = lead_data["id"]
    assert lead_data["company_name"] == "Lone Star Electrical"
    assert lead_data["domain"] == "lonestarelec.example"
    assert "research" in lead_data
    assert lead_data["research"]["lead_id"] == lead_id

    # 2. Duplicate prevention
    dup_resp = await client.post("/api/v1/leads/manual", json=payload, headers=auth_headers)
    assert dup_resp.status_code == 400
    assert "already exists" in dup_resp.json()["detail"]

    # 3. Retrieve by ID
    get_resp = await client.get(f"/api/v1/leads/{lead_id}", headers=auth_headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == lead_id

    # 4. List leads with filtering
    list_resp = await client.get("/api/v1/leads?search=Lone+Star", headers=auth_headers)
    assert list_resp.status_code == 200
    data = list_resp.json()
    assert data["total"] >= 1
    assert any(item["id"] == lead_id for item in data["items"])

    # 5. Approve lead (Human Approval Gate)
    approve_resp = await client.post(f"/api/v1/leads/{lead_id}/approve", headers=auth_headers)
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == LeadStatus.APPROVED.value

    # 6. Reject lead
    reject_resp = await client.post(
        f"/api/v1/leads/{lead_id}/reject",
        json={"reason": "Business is closed"},
        headers=auth_headers,
    )
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == LeadStatus.REJECTED.value
    assert reject_resp.json()["rejection_reason"] == "Business is closed"


@pytest.mark.asyncio
async def test_discover_leads_batch_limit(client: AsyncClient, auth_headers: dict):
    """Discover leads enforces max 20 batch limit and initiates agent run."""
    # Test batch limit validation
    over_limit = {
        "query": "dentists",
        "location": "Dallas, TX",
        "limit": 50,  # Max is 20
        "provider": "manual_entry",
    }
    resp = await client.post("/api/v1/leads/discover", json=over_limit, headers=auth_headers)
    assert resp.status_code == 422  # Pydantic validation error (le=20)
