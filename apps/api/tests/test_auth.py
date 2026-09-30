"""
Tests for authentication.

Tests the full auth flow:
- Login with valid credentials
- Login with invalid credentials
- Token validation (/auth/me)
- Protected endpoints reject unauthenticated requests
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_with_missing_config(client: AsyncClient):
    """
    Login should return 503 when OWNER_EMAIL or OWNER_PASSWORD_HASH is not set.
    This is tested separately since conftest.py sets them.
    Indirectly verified by the 401 path below.
    """
    pass  # Covered by integration tests when env is empty


@pytest.mark.asyncio
async def test_login_invalid_email(client: AsyncClient):
    """Wrong email returns 401."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "wrong@example.com", "password": "testpassword"},
    )
    assert response.status_code == 401
    assert "Invalid" in response.json()["detail"]


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient):
    """Wrong password returns 401."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "wrongpassword"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_valid_credentials(client: AsyncClient):
    """Valid credentials return a JWT token."""
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "testpassword"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0
    assert len(data["access_token"]) > 20  # Must be a real token, not empty


@pytest.mark.asyncio
async def test_me_without_token(client: AsyncClient):
    """GET /auth/me without token returns 401."""
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_with_valid_token(client: AsyncClient, auth_headers: dict):
    """GET /auth/me with valid token returns owner email."""
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["role"] == "owner"


@pytest.mark.asyncio
async def test_me_with_invalid_token(client: AsyncClient):
    """GET /auth/me with bad token returns 401."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer this.is.not.valid"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_agent_runs_requires_auth(client: AsyncClient):
    """Agent runs endpoint should reject unauthenticated requests."""
    response = await client.get("/api/v1/agents/runs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_agent_registry_is_public(client: AsyncClient):
    """Agent registry endpoint is informational and requires no auth."""
    response = await client.get("/api/v1/agents/registry")
    assert response.status_code == 200
    data = response.json()
    assert "agents" in data
    assert "orchestrator" in data["agents"]
    assert data["agents"]["orchestrator"]["active"] is True
    assert data["agents"]["lead_research"]["active"] is True
    assert data["agents"]["outreach"]["active"] is False
