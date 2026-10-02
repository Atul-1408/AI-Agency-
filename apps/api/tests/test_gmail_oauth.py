"""
Phase 4 — Stage 4.2: Gmail Health & Connection Management Test Suite.

Comprehensive mocked test suite verifying:
1. successful health check -> 200 CONNECTED
2. invalid_grant -> 200 DISCONNECTED (INVALID_GRANT)
3. HTTP 401 -> 200 DISCONNECTED (UNAUTHORIZED)
4. HTTP 403 -> 200 DISCONNECTED (FORBIDDEN)
5. HTTP 429 -> 200 ERROR (RATE_LIMITED)
6. Google 5xx -> 200 ERROR (GOOGLE_5XX)
7. network timeout -> 200 ERROR (TIMEOUT)
8. malformed Google response -> 200 ERROR (MALFORMED_RESPONSE)
9. token decryption failure -> 200 ERROR (DECRYPTION_FAILED)
10. missing encryption key -> fail closed
11. successful disconnect -> 200 DISCONNECTED
12. revoke failure but local disconnect succeeds
13. status endpoint metadata safety
14. unauthorized status -> 401
15. unauthorized health check -> 401
16. IDOR protection across all Gmail endpoints
17. OAuth state replay protection -> 400
18. expired state -> 400
19. wrong owner state -> 400
20. wrong purpose state -> 400
21. callback invalid code -> 400
22. account mismatch collision -> 409
23. audit token sanitization
24. no send endpoint exists (inviolable phase boundary)
25. health check rate limiting (10s cooldown -> 429)

SECURITY GUARANTEES:
- Strictly mocked: 0 external requests to Google servers
- Minimal OAuth scopes only (gmail.send, openid, email)
- No email dispatch, send, SMTP, or inbox-reading endpoints exist
- No plaintext refresh tokens stored or logged
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient, Response, TimeoutException
from jose import jwt
from sqlalchemy import select

from core.config import settings
from main import app as fastapi_app
from models import AgentRun, AgentRunStatus
from models.outreach import ConsumedOAuthState, GmailAccount, GmailConnectionStatus
from routers.auth import _create_access_token
from services.gmail_credential_service import GmailCredentialService, HealthAssessmentResult
from services.gmail_oauth_service import (
    GmailOAuthConfigError,
    GmailOAuthService,
    OAuthExchangeError,
    OAuthStateInvalidError,
    SAFE_SCOPE_LABELS,
)
from services.token_encryption import (
    TokenDecryptionError,
    TokenEncryptionKeyMissingError,
    TokenEncryptionService,
)
from tests.conftest import TestSessionLocal


@pytest.fixture(autouse=True)
def setup_oauth_env_settings():
    """Ensure test environment has OAuth configuration set for the test run."""
    original_client_id = settings.GOOGLE_CLIENT_ID
    original_client_secret = settings.GOOGLE_CLIENT_SECRET
    original_redirect_uri = settings.GOOGLE_REDIRECT_URI
    original_encryption_key = settings.GMAIL_TOKEN_ENCRYPTION_KEY

    settings.GOOGLE_CLIENT_ID = "mock_client_id_123.apps.googleusercontent.com"
    settings.GOOGLE_CLIENT_SECRET = "mock_client_secret_xyz"
    settings.GOOGLE_REDIRECT_URI = "http://testserver/api/v1/gmail/callback"
    settings.GMAIL_TOKEN_ENCRYPTION_KEY = "test_encryption_key_32_bytes_long_secret!"

    yield

    settings.GOOGLE_CLIENT_ID = original_client_id
    settings.GOOGLE_CLIENT_SECRET = original_client_secret
    settings.GOOGLE_REDIRECT_URI = original_redirect_uri
    settings.GMAIL_TOKEN_ENCRYPTION_KEY = original_encryption_key


@contextmanager
def mock_google_service_http(
    post_response: Response = None,
    get_response: Response = None,
    post_side_effect = None,
):
    """
    Mock ONLY the httpx.AsyncClient instances inside Gmail services,
    leaving the test client's ASGI transport completely intact.
    """
    mock_instance = AsyncMock()
    if post_side_effect is not None:
        mock_instance.post.side_effect = post_side_effect
    elif post_response is not None:
        mock_instance.post.return_value = post_response

    if get_response is not None:
        mock_instance.get.return_value = get_response

    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.__aexit__.return_value = None

    with patch("services.gmail_oauth_service.httpx.AsyncClient", return_value=mock_instance), \
         patch("services.gmail_credential_service.httpx.AsyncClient", return_value=mock_instance):
        yield mock_instance


# ── 1. Successful Health Check ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_health_check(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/gmail/health-check returns 200 CONNECTED when token refresh succeeds."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("valid_refresh_token_123")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    mock_resp = Response(
        status_code=200,
        json={"access_token": "ya29.new_refreshed_access_token", "expires_in": 3600},
    )

    with mock_google_service_http(post_response=mock_resp):
        response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is True
        assert data["status"] == "CONNECTED"
        assert data["email"] == "test@gmail.com"

    # Verify database update and audit event
    async with TestSessionLocal() as session:
        updated = await session.scalar(select(GmailAccount).where(GmailAccount.owner_id == "test@example.com"))
        assert updated.connection_status == GmailConnectionStatus.CONNECTED
        assert updated.last_error_at is None
        assert updated.last_error_code is None

        audit = await session.scalar(
            select(AgentRun)
            .where(AgentRun.agent_name == "gmail_oauth")
            .where(AgentRun.input_data["action"].as_string() == "gmail_health_success")
        )
        assert audit is not None
        assert audit.status == AgentRunStatus.COMPLETED


# ── 2. Invalid Grant (Revoked Credentials) ────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_invalid_grant(client: AsyncClient, auth_headers: dict):
    """Google 400 invalid_grant marks connection DISCONNECTED."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("revoked_refresh_token")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    mock_resp = Response(
        status_code=400,
        json={"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
    )

    with mock_google_service_http(post_response=mock_resp):
        response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is False
        assert data["status"] == "DISCONNECTED"
        assert data["error_code"] == "INVALID_GRANT"

    async with TestSessionLocal() as session:
        updated = await session.scalar(select(GmailAccount).where(GmailAccount.owner_id == "test@example.com"))
        assert updated.connection_status == GmailConnectionStatus.DISCONNECTED
        assert updated.last_error_code == "INVALID_GRANT"
        assert updated.last_error_at is not None


# ── 3. HTTP 401 Unauthorized ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_http_401(client: AsyncClient, auth_headers: dict):
    """Google 401 Unauthorized marks connection DISCONNECTED."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("unauthorized_token")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    with mock_google_service_http(post_response=Response(status_code=401)):
        response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is False
        assert data["status"] == "DISCONNECTED"
        assert data["error_code"] == "UNAUTHORIZED"


# ── 4. HTTP 403 Forbidden ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_http_403(client: AsyncClient, auth_headers: dict):
    """Google 403 Forbidden marks connection DISCONNECTED."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("forbidden_token")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    with mock_google_service_http(post_response=Response(status_code=403)):
        response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is False
        assert data["status"] == "DISCONNECTED"
        assert data["error_code"] == "FORBIDDEN"


# ── 5. HTTP 429 Rate Limit (Temporary Error) ───────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_http_429_rate_limit(client: AsyncClient, auth_headers: dict):
    """Google 429 Rate Limited marks connection ERROR (not permanent disconnect)."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("rate_limited_token")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    with mock_google_service_http(post_response=Response(status_code=429)):
        response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is False
        assert data["status"] == "ERROR"
        assert data["error_code"] == "RATE_LIMITED"


# ── 6. Google 5xx Server Error (Temporary Error) ──────────────────────────────

@pytest.mark.asyncio
async def test_health_check_google_5xx(client: AsyncClient, auth_headers: dict):
    """Google 503 Server Error marks connection ERROR (not permanent disconnect)."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("token_5xx")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    with mock_google_service_http(post_response=Response(status_code=503, text="Service Unavailable")):
        response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is False
        assert data["status"] == "ERROR"
        assert data["error_code"] == "GOOGLE_5XX"


# ── 7. Network Timeout (Temporary Error) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_network_timeout(client: AsyncClient, auth_headers: dict):
    """Network timeout during Google health check marks connection ERROR."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("timeout_token")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    with mock_google_service_http(post_side_effect=TimeoutException("Connection timed out")):
        response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is False
        assert data["status"] == "ERROR"
        assert data["error_code"] == "TIMEOUT"


# ── 8. Malformed Google Response ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_malformed_response(client: AsyncClient, auth_headers: dict):
    """Non-JSON response from Google marks connection ERROR."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("malformed_token")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    with mock_google_service_http(post_response=Response(status_code=200, content=b"<html>Bad Gateway</html>")):
        response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is False
        assert data["status"] == "ERROR"
        assert data["error_code"] == "MALFORMED_RESPONSE"


# ── 9. Token Decryption Failure ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_token_decryption_failure(client: AsyncClient, auth_headers: dict):
    """Corrupted ciphertext marks connection ERROR without crashing."""
    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token="corrupted_garbage_base64_payload==",
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["is_healthy"] is False
    assert data["status"] == "ERROR"
    assert data["error_code"] == "DECRYPTION_FAILED"


# ── 10. Missing Encryption Key ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_check_missing_encryption_key(client: AsyncClient, auth_headers: dict):
    """Unconfigured encryption key fails closed (status ERROR)."""
    settings.GMAIL_TOKEN_ENCRYPTION_KEY = ""

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token="some_encrypted_token",
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=30),
        )
        session.add(account)
        await session.commit()

    response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["is_healthy"] is False
    assert data["status"] == "ERROR"
    assert data["error_code"] == "KEY_MISSING"


# ── 11. Successful Disconnect ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_disconnect(client: AsyncClient, auth_headers: dict):
    """Disconnect purges encrypted refresh token and marks account DISCONNECTED."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("token_to_purge")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="disconnect_me@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
        )
        session.add(account)
        await session.commit()

    with mock_google_service_http(post_response=Response(status_code=200)):
        response = await client.post("/api/v1/gmail/disconnect", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "DISCONNECTED"

    async with TestSessionLocal() as session:
        updated = await session.scalar(select(GmailAccount).where(GmailAccount.owner_id == "test@example.com"))
        assert updated.connection_status == GmailConnectionStatus.DISCONNECTED
        assert updated.encrypted_refresh_token == ""

        audit = await session.scalar(
            select(AgentRun)
            .where(AgentRun.agent_name == "gmail_oauth")
            .where(AgentRun.input_data["action"].as_string() == "gmail_disconnected")
        )
        assert audit is not None
        assert audit.status == AgentRunStatus.COMPLETED


# ── 12. Revoke Failure But Local Disconnect Succeeds ──────────────────────────

@pytest.mark.asyncio
async def test_revoke_failure_local_disconnect_succeeds(client: AsyncClient, auth_headers: dict):
    """If Google's revoke endpoint fails, local disconnect must still succeed completely."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("token_already_revoked")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="disconnect_err@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
        )
        session.add(account)
        await session.commit()

    with mock_google_service_http(post_response=Response(status_code=500, text="Revocation error")):
        response = await client.post("/api/v1/gmail/disconnect", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["status"] == "DISCONNECTED"

    async with TestSessionLocal() as session:
        updated = await session.scalar(select(GmailAccount).where(GmailAccount.owner_id == "test@example.com"))
        assert updated.connection_status == GmailConnectionStatus.DISCONNECTED
        assert updated.encrypted_refresh_token == ""


# ── 13. Status Endpoint Safety ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_endpoint_safety(client: AsyncClient, auth_headers: dict):
    """GET /api/v1/gmail/status exposes only safe metadata; never leaks tokens or keys."""
    encryption_service = TokenEncryptionService()
    secret_refresh = "1//04VERY_CONFIDENTIAL_TOKEN_DO_NOT_REVEAL"
    encrypted_token = encryption_service.encrypt(secret_refresh)

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="status_owner@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            last_health_check=datetime.now(timezone.utc),
        )
        session.add(account)
        await session.commit()

    response = await client.get("/api/v1/gmail/status", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is True
    assert data["email"] == "status_owner@gmail.com"
    assert data["connection_status"] == "CONNECTED"
    assert data["scopes"] == SAFE_SCOPE_LABELS
    assert secret_refresh not in response.text
    assert "encrypted_refresh_token" not in data


# ── 14. Unauthorized Status -> 401 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthorized_status(client: AsyncClient):
    """GET /api/v1/gmail/status without Bearer token returns 401."""
    response = await client.get("/api/v1/gmail/status")
    assert response.status_code == 401


# ── 15. Unauthorized Health Check -> 401 ──────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthorized_health_check(client: AsyncClient):
    """POST /api/v1/gmail/health-check without Bearer token returns 401."""
    response = await client.post("/api/v1/gmail/health-check")
    assert response.status_code == 401


# ── 16. IDOR Protection ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idor_protection(client: AsyncClient):
    """Foreign owner token returns 403 Forbidden across all endpoints."""
    imposter_token, _ = _create_access_token("attacker@hostile.com")
    headers = {"Authorization": f"Bearer {imposter_token}"}

    assert (await client.get("/api/v1/gmail/connect", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/gmail/status", headers=headers)).status_code == 403
    assert (await client.post("/api/v1/gmail/disconnect", headers=headers)).status_code == 403
    assert (await client.post("/api/v1/gmail/health-check", headers=headers)).status_code == 403


# ── 17. OAuth State Replay Protection ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_oauth_state_replay_protection(client: AsyncClient, auth_headers: dict):
    """Consuming the same OAuth state twice must be rejected with 400."""
    service = GmailOAuthService()
    state = service.generate_state("test@example.com")

    mock_post_resp = Response(
        status_code=200,
        json={"access_token": "ya29.first_token", "refresh_token": "1//04first_refresh"},
    )
    mock_get_resp = Response(
        status_code=200,
        json={"email": "replay_test@gmail.com"},
    )

    with mock_google_service_http(post_response=mock_post_resp, get_response=mock_get_resp):
        # First consumption -> Success
        res1 = await client.get(
            f"/api/v1/gmail/callback?code=valid_code_1&state={state}",
            headers=auth_headers,
        )
        assert res1.status_code == 200

        # Second consumption of identical state -> 400 Replay Attack
        res2 = await client.get(
            f"/api/v1/gmail/callback?code=valid_code_2&state={state}",
            headers=auth_headers,
        )
        assert res2.status_code == 400
        assert "replay attack detected" in res2.json().get("detail", "")


# ── 18. Expired State ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_expired_oauth_state(client: AsyncClient, auth_headers: dict):
    """Expired OAuth state token must be rejected with 400."""
    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": "test@example.com",
        "nonce": "test_nonce",
        "jti": "expired_jti_123",
        "purpose": "gmail_oauth_state",
        "iat": int((now - timedelta(minutes=20)).timestamp()),
        "exp": int((now - timedelta(minutes=10)).timestamp()),
    }
    expired_state = jwt.encode(expired_payload, settings.APP_SECRET, algorithm="HS256")

    response = await client.get(
        f"/api/v1/gmail/callback?code=mock_code&state={expired_state}",
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "expired" in response.json().get("detail", "").lower()


# ── 19. Wrong Owner State ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_owner_state(client: AsyncClient, auth_headers: dict):
    """State issued to owner A rejected when presented by owner B."""
    service = GmailOAuthService()
    state_for_other = service.generate_state("other_owner@agency.com")

    # Authenticated user is test@example.com (from auth_headers), state is other_owner@agency.com
    response = await client.get(
        f"/api/v1/gmail/callback?code=mock_code&state={state_for_other}",
        headers=auth_headers,
    )
    assert response.status_code in (400, 403)


# ── 20. Wrong Purpose State ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wrong_purpose_state(client: AsyncClient, auth_headers: dict):
    """JWT with wrong purpose claim rejected with 400."""
    payload = {
        "sub": "test@example.com",
        "nonce": "test_nonce",
        "jti": "jti_wrong_purpose",
        "purpose": "unrelated_auth_action",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()),
    }
    state = jwt.encode(payload, settings.APP_SECRET, algorithm="HS256")

    response = await client.get(
        f"/api/v1/gmail/callback?code=mock_code&state={state}",
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "purpose" in response.json().get("detail", "").lower()


# ── 21. Callback Invalid Code ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_callback_invalid_code(client: AsyncClient, auth_headers: dict):
    """Google rejecting authorization code returns 400."""
    service = GmailOAuthService()
    state = service.generate_state("test@example.com")

    with mock_google_service_http(post_response=Response(status_code=400, json={"error": "invalid_grant"})):
        response = await client.get(
            f"/api/v1/gmail/callback?code=bad_code_123&state={state}",
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert "Failed to exchange authorization code" in response.json().get("detail", "")


# ── 22. Account Mismatch / Collision ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_account_mismatch_collision(client: AsyncClient, auth_headers: dict):
    """Connecting a Google email already linked to another owner is rejected with 409."""
    # Pre-populate another owner's account with google_email
    async with TestSessionLocal() as session:
        other_account = GmailAccount(
            owner_id="foreign_owner@otheragency.com",
            google_email="claimed@gmail.com",
            encrypted_refresh_token="some_token",
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
        )
        session.add(other_account)
        await session.commit()

    service = GmailOAuthService()
    state = service.generate_state("test@example.com")

    mock_post_resp = Response(
        status_code=200,
        json={"access_token": "ya29.tok", "refresh_token": "1//04ref"},
    )
    mock_get_resp = Response(
        status_code=200,
        json={"email": "claimed@gmail.com"},
    )

    with mock_google_service_http(post_response=mock_post_resp, get_response=mock_get_resp):
        response = await client.get(
            f"/api/v1/gmail/callback?code=valid_code&state={state}",
            headers=auth_headers,
        )
        assert response.status_code == 409
        assert "already linked" in response.json().get("detail", "").lower()


# ── 23. Audit Token Sanitization ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_audit_token_sanitization(client: AsyncClient, auth_headers: dict):
    """Verify that tokens and keys are NEVER recorded in agent_runs table."""
    secret_refresh = "1//04NEVER_RECORD_IN_AUDIT_LOG_REFRESH"
    secret_access = "ya29.NEVER_RECORD_IN_AUDIT_LOG_ACCESS"

    service = GmailOAuthService()
    state = service.generate_state("test@example.com")

    mock_post_resp = Response(
        status_code=200,
        json={"access_token": secret_access, "refresh_token": secret_refresh},
    )
    mock_get_resp = Response(
        status_code=200,
        json={"email": "audit_safe@gmail.com"},
    )

    with mock_google_service_http(post_response=mock_post_resp, get_response=mock_get_resp):
        await client.get(
            f"/api/v1/gmail/callback?code=mock_code&state={state}",
            headers=auth_headers,
        )

    async with TestSessionLocal() as session:
        runs = (await session.scalars(select(AgentRun).where(AgentRun.agent_name == "gmail_oauth"))).all()
        for r in runs:
            content_str = str(r.input_data) + str(r.output_data)
            assert secret_refresh not in content_str
            assert secret_access not in content_str


# ── 24. No Send Endpoint Exists (Phase Boundary Inviolability) ────────────────

@pytest.mark.asyncio
async def test_no_send_endpoint_exists(client: AsyncClient, auth_headers: dict):
    """
    CRITICAL PHASE BOUNDARY VERIFICATION:
    Confirm that no Gmail sending, message creation, or dispatch endpoint exists in the application.
    """
    # Verify via HTTP request that sending endpoints return 404
    send_res = await client.post("/api/v1/gmail/send", headers=auth_headers, json={"to": "lead@test.com"})
    assert send_res.status_code in (404, 405)

    dispatch_res = await client.post("/api/v1/gmail/dispatch", headers=auth_headers, json={})
    assert dispatch_res.status_code in (404, 405)

    messages_res = await client.post("/api/v1/gmail/messages", headers=auth_headers, json={})
    assert messages_res.status_code in (404, 405)

    # Verify route registry: no route contains 'send' in the gmail prefix
    for route in fastapi_app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/api/v1/gmail"):
            assert "/send" not in path
            assert "/messages" not in path
            assert "/dispatch" not in path


# ── 25. Health Check Rate Limiting (10-second Cooldown) ───────────────────────

@pytest.mark.asyncio
async def test_health_check_rate_limiting(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/gmail/health-check triggers 429 when called in rapid succession."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("valid_token")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
            # Set last_health_check to just 2 seconds ago
            last_health_check=datetime.now(timezone.utc) - timedelta(seconds=2),
        )
        session.add(account)
        await session.commit()

    # Rapid call without force -> 429
    res = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
    assert res.status_code == 429
    assert "rate limit exceeded" in res.json().get("detail", "").lower()

    # Rapid call with force=True -> succeeds and bypasses rate limit
    mock_resp = Response(
        status_code=200,
        json={"access_token": "ya29.forced_token", "expires_in": 3600},
    )
    with mock_google_service_http(post_response=mock_resp):
        res_forced = await client.post("/api/v1/gmail/health-check?force=true", headers=auth_headers)
        assert res_forced.status_code == 200
        assert res_forced.json()["status"] == "CONNECTED"
