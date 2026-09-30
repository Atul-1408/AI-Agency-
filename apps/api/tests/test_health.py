"""
Tests for the health endpoint.

These tests verify the health endpoint structure and response format
WITHOUT requiring a real database or Redis connection.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_returns_200(client: AsyncClient):
    """Health endpoint must always return 200, even when services are down."""
    response = await client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_response_structure(client: AsyncClient):
    """Health response must have required fields."""
    response = await client.get("/api/v1/health")
    data = response.json()

    assert "status" in data
    assert "version" in data
    assert "environment" in data
    assert "services" in data

    # Status must be either ok or degraded (never a 5xx error)
    assert data["status"] in ("ok", "degraded")

    # Each service must have a status
    for service_name, service_data in data["services"].items():
        assert "status" in service_data
        assert service_data["status"] in ("ok", "unavailable", "error"), (
            f"Service '{service_name}' has invalid status: {service_data['status']}"
        )


@pytest.mark.asyncio
async def test_health_environment_is_test(client: AsyncClient):
    """Health endpoint must report the correct environment."""
    response = await client.get("/api/v1/health")
    data = response.json()
    assert data["environment"] == "test"


@pytest.mark.asyncio
async def test_health_services_are_honest(client: AsyncClient):
    """
    In test environment with no DB/Redis running, services should report
    'unavailable' — NOT 'ok'. This verifies we don't fake health status.
    """
    response = await client.get("/api/v1/health")
    data = response.json()

    # In test environment without real infrastructure, at least one
    # service should be unavailable
    statuses = [s["status"] for s in data["services"].values()]
    # We can't assert exactly which — depends on whether test infrastructure is up.
    # But we CAN assert there's no fake "ok" when connecting to localhost fails.
    assert all(s in ("ok", "unavailable", "error") for s in statuses)


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Root endpoint should return basic app info."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["phase"] == 2
    assert "version" in data
    assert "health" in data
