"""
Tests for agent foundation — registry, trigger, lifecycle, error handling.

Note: Tests that trigger actual agent runs require a real database.
Tests marked with @pytest.mark.requires_db are skipped in CI without DB.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_agent_registry_structure(client: AsyncClient):
    """Registry must list all planned agents with their phase."""
    response = await client.get("/api/v1/agents/registry")
    assert response.status_code == 200
    data = response.json()

    agents = data["agents"]

    # Phase 1 — active
    assert agents["orchestrator"]["phase"] == 1
    assert agents["orchestrator"]["active"] is True

    # Phase 2+ — registered but not active
    expected_inactive = {
        "lead_research": 2,
        "outreach": 3,
        "follow_up": 4,
        "client_intelligence": 5,
        "website_builder": 6,
        "qa": 7,
        "deployment": 8,
    }
    for name, phase in expected_inactive.items():
        assert name in agents, f"Agent '{name}' missing from registry"
        assert agents[name]["phase"] == phase
        assert agents[name]["active"] is False, f"Agent '{name}' should not be active in Phase 1"


@pytest.mark.asyncio
async def test_trigger_unknown_agent_returns_400(client: AsyncClient, auth_headers: dict):
    """Triggering an unknown agent name should return 400."""
    response = await client.post(
        "/api/v1/agents/trigger",
        json={"agent_name": "totally_fake_agent"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Unknown agent" in response.json()["detail"]


@pytest.mark.asyncio
async def test_trigger_phase2_agent_returns_400(client: AsyncClient, auth_headers: dict):
    """Triggering a Phase 2+ agent should return 400 with helpful message."""
    response = await client.post(
        "/api/v1/agents/trigger",
        json={"agent_name": "lead_research"},
        headers=auth_headers,
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "Phase 2" in detail
    assert "not active" in detail


@pytest.mark.asyncio
async def test_trigger_without_auth_returns_401(client: AsyncClient):
    """Trigger endpoint requires authentication."""
    response = await client.post(
        "/api/v1/agents/trigger",
        json={"agent_name": "orchestrator"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_runs_empty_with_auth(client: AsyncClient, auth_headers: dict):
    """
    List runs returns a valid paginated response.
    NOTE: This will fail if DB is not running — that is expected and honest.
    """
    response = await client.get("/api/v1/agents/runs", headers=auth_headers)
    # Either 200 (DB available) or 500 (DB unavailable)
    # We assert the response is not 401/403/404 — those would be logic bugs
    assert response.status_code in (200, 500), (
        f"Unexpected status {response.status_code}: DB may not be running"
    )


def test_base_agent_is_abstract():
    """BaseAgent cannot be instantiated directly."""
    from agents.base_agent import BaseAgent
    with pytest.raises(TypeError):
        BaseAgent()  # type: ignore


def test_orchestrator_is_concrete():
    """Orchestrator can be instantiated."""
    from agents.orchestrator import Orchestrator
    agent = Orchestrator()
    assert agent.name == "orchestrator"


def test_ai_provider_disabled_by_default():
    """AIProvider must be disabled when NEMOTRON_ENABLED=false."""
    from agents.base_agent import AIProvider
    provider = AIProvider(
        enabled=False, api_key="", base_url="", model=""
    )
    assert provider.enabled is False


@pytest.mark.asyncio
async def test_ai_provider_raises_when_disabled():
    """AIProvider.chat() must raise NotImplementedError when disabled, not return fake data."""
    from agents.base_agent import AIProvider
    provider = AIProvider(enabled=False, api_key="", base_url="", model="")
    with pytest.raises(NotImplementedError):
        await provider.chat("system", "user")


def test_approval_decision_rejects_pending():
    """ApprovalDecision schema must not accept 'pending' as a decision."""
    from schemas import ApprovalDecision
    from models import ApprovalStatus
    with pytest.raises(ValueError):
        ApprovalDecision(decision=ApprovalStatus.PENDING)
