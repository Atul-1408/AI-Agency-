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


@pytest.mark.asyncio
async def test_multi_location_deduplication(client: AsyncClient, auth_headers: dict):
    """
    Verify location-aware deduplication:
    1. Same business, different legitimate locations -> allowed as separate leads
    2. Same domain, different legitimate locations -> allowed as separate leads
    3. Same domain, same location -> rejected as duplicate
    4. Different businesses sharing a domain -> allowed as separate leads
    5. Same phone number -> rejected as duplicate
    """
    # 1. Location A: Mumbai
    lead_mumbai = {
        "company_name": "ABC Plumbing Services",
        "website_url": "https://www.abcplumbing.example",
        "phone": "+91 22 5555 1111",
        "address": "Bandra West",
        "city": "Mumbai",
        "industry": "Plumbing",
    }
    resp_mumbai = await client.post("/api/v1/leads/manual", json=lead_mumbai, headers=auth_headers)
    assert resp_mumbai.status_code == 201
    mumbai_data = resp_mumbai.json()
    assert mumbai_data["city"] == "Mumbai"

    # 2. Same business & domain, different location: Pune -> MUST BE ALLOWED as separate lead
    lead_pune = {
        "company_name": "ABC Plumbing Services",
        "website_url": "https://www.abcplumbing.example",
        "phone": "+91 20 8888 2222",
        "address": "Koregaon Park",
        "city": "Pune",
        "industry": "Plumbing",
    }
    resp_pune = await client.post("/api/v1/leads/manual", json=lead_pune, headers=auth_headers)
    assert resp_pune.status_code == 201
    pune_data = resp_pune.json()
    assert pune_data["id"] != mumbai_data["id"]
    assert pune_data["domain"] == mumbai_data["domain"]
    assert pune_data["city"] == "Pune"

    # 3. Same business & domain & same location (Mumbai) -> REJECTED as duplicate
    lead_mumbai_dup = {
        "company_name": "ABC Plumbing Services",
        "website_url": "https://www.abcplumbing.example",
        "phone": "+91 22 5555 9999",
        "address": "Bandra West",
        "city": "Mumbai",
        "industry": "Plumbing",
    }
    resp_mumbai_dup = await client.post("/api/v1/leads/manual", json=lead_mumbai_dup, headers=auth_headers)
    assert resp_mumbai_dup.status_code == 400
    assert "already exists" in resp_mumbai_dup.json()["detail"]

    # 4. Different business sharing domain (e.g. portal or sub-tenant) -> ALLOWED as separate lead
    different_biz = {
        "company_name": "Zenith Electric",
        "website_url": "https://www.abcplumbing.example",
        "phone": "+91 22 7777 3333",
        "address": "Andheri East",
        "city": "Mumbai",
        "industry": "Electrical",
    }
    resp_diff = await client.post("/api/v1/leads/manual", json=different_biz, headers=auth_headers)
    assert resp_diff.status_code == 201
    assert resp_diff.json()["company_name"] == "Zenith Electric"

    # 5. Same phone number submitted -> REJECTED as duplicate
    dup_phone_lead = {
        "company_name": "ABC Support Desk",
        "website_url": "https://www.abc-support.example",
        "phone": "+91 20 8888 2222",  # Same as lead_pune
        "address": "Shivaji Nagar",
        "city": "Pune",
        "industry": "Plumbing",
    }
    resp_dup_phone = await client.post("/api/v1/leads/manual", json=dup_phone_lead, headers=auth_headers)
    assert resp_dup_phone.status_code == 400
    assert "already exists" in resp_dup_phone.json()["detail"]
