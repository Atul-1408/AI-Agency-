"""
Phase 4 — Stage 4.1: Gmail OAuth Foundation Test Suite.

Comprehensive mocked test suite verifying:
1. unauthenticated connect -> 401
2. unauthorized owner -> 403
3. valid OAuth state
4. invalid OAuth state
5. expired OAuth state
6. state-owner mismatch
7. authorization code exchange
8. Google identity retrieval
9. refresh-token encryption
10. refresh-token decryption
11. missing encryption key -> fail closed
12. token never appears in API response
13. token never appears in logs
14. Gmail status
15. Gmail disconnected status
16. Gmail health failure
17. disconnect
18. IDOR protection
19. OAuth callback failure
20. complete end-to-end mocked OAuth flow

SECURITY VERIFICATIONS:
- Strictly mocked: 0 external requests to Google servers
- Minimal OAuth scopes only (gmail.send, openid, email)
- No plaintext refresh tokens stored or logged
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient, Response
from jose import jwt
from sqlalchemy import select

from core.config import settings
from models import AgentRun, AgentRunStatus
from models.outreach import GmailAccount, GmailConnectionStatus
from routers.auth import _create_access_token
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
def mock_google_service_http(post_response: Response = None, get_response: Response = None):
    """
    Mock ONLY the httpx.AsyncClient inside services.gmail_oauth_service,
    leaving the test client's ASGI transport completely intact.
    """
    mock_instance = AsyncMock()
    if post_response is not None:
        mock_instance.post.return_value = post_response
    if get_response is not None:
        mock_instance.get.return_value = get_response
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.__aexit__.return_value = None

    with patch("services.gmail_oauth_service.httpx.AsyncClient", return_value=mock_instance):
        yield mock_instance


# ── 1. Unauthenticated connect -> 401 ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthenticated_connect_returns_401(client: AsyncClient):
    """GET /api/v1/gmail/connect without Bearer token must return 401 Unauthorized."""
    response = await client.get("/api/v1/gmail/connect")
    assert response.status_code == 401
    assert "Authorization header required" in response.json().get("detail", "")


# ── 2. Unauthorized owner -> 403 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unauthorized_owner_returns_403(client: AsyncClient):
    """Foreign owner token must be rejected with 403 Forbidden."""
    imposter_token, _ = _create_access_token("imposter@foreign-agency.com")
    headers = {"Authorization": f"Bearer {imposter_token}"}

    response = await client.get("/api/v1/gmail/connect", headers=headers)
    assert response.status_code == 403
    assert "Forbidden" in response.json().get("detail", "")


# ── 3. Valid OAuth state ──────────────────────────────────────────────────────

def test_valid_oauth_state_generation_and_validation():
    """Valid OAuth state generates proper JWT bound to owner and decodes cleanly."""
    service = GmailOAuthService()
    state = service.generate_state("test@example.com")
    assert state is not None

    bound_owner = service.validate_state(state, expected_owner_email="test@example.com")
    assert bound_owner == "test@example.com"


# ── 4. Invalid OAuth state ────────────────────────────────────────────────────

def test_invalid_oauth_state():
    """Tampered or invalid OAuth state raises OAuthStateInvalidError."""
    service = GmailOAuthService()
    with pytest.raises(OAuthStateInvalidError):
        service.validate_state("not_a_valid_jwt_token")

    payload = {"sub": "test@example.com", "purpose": "wrong_purpose", "exp": 9999999999}
    wrong_purpose_token = jwt.encode(payload, settings.APP_SECRET, algorithm="HS256")
    with pytest.raises(OAuthStateInvalidError):
        service.validate_state(wrong_purpose_token)


# ── 5. Expired OAuth state ────────────────────────────────────────────────────

def test_expired_oauth_state():
    """Expired OAuth state token raises OAuthStateInvalidError."""
    service = GmailOAuthService()
    now = datetime.now(timezone.utc)
    expired_payload = {
        "sub": "test@example.com",
        "nonce": "test_nonce",
        "purpose": "gmail_oauth_state",
        "iat": int((now - timedelta(minutes=20)).timestamp()),
        "exp": int((now - timedelta(minutes=10)).timestamp()),
    }
    expired_state = jwt.encode(expired_payload, settings.APP_SECRET, algorithm="HS256")

    with pytest.raises(OAuthStateInvalidError, match="expired"):
        service.validate_state(expired_state)


# ── 6. State-owner mismatch ───────────────────────────────────────────────────

def test_state_owner_mismatch():
    """State issued to owner A rejected if claimed by owner B."""
    service = GmailOAuthService()
    state_for_a = service.generate_state("owner_a@agency.com")

    with pytest.raises(OAuthStateInvalidError, match="mismatch"):
        service.validate_state(state_for_a, expected_owner_email="owner_b@agency.com")


# ── 7. Authorization code exchange ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_authorization_code_exchange_mocked():
    """Exchange authorization code via mocked Google token endpoint."""
    service = GmailOAuthService()

    mock_resp = Response(
        status_code=200,
        json={
            "access_token": "ya29.mock_access_token_123",
            "refresh_token": "1//04mock_refresh_token_456",
            "expires_in": 3600,
            "token_type": "Bearer",
        },
    )

    with mock_google_service_http(post_response=mock_resp) as mock_http:
        tokens = await service.exchange_code_for_tokens("mock_auth_code_789")

        assert tokens["access_token"] == "ya29.mock_access_token_123"
        assert tokens["refresh_token"] == "1//04mock_refresh_token_456"
        assert mock_http.post.call_count == 1
        call_args = mock_http.post.call_args
        assert call_args[0][0] == "https://oauth2.googleapis.com/token"
        assert call_args[1]["data"]["code"] == "mock_auth_code_789"


# ── 8. Google identity retrieval ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_google_identity_retrieval_mocked():
    """Retrieve Google user email via mocked userinfo endpoint."""
    service = GmailOAuthService()

    mock_resp = Response(
        status_code=200,
        json={"email": "verified_owner@gmail.com", "verified_email": True},
    )

    with mock_google_service_http(get_response=mock_resp) as mock_http:
        email = await service.get_user_identity("ya29.mock_access_token_123")

        assert email == "verified_owner@gmail.com"
        assert mock_http.get.call_count == 1
        assert "Authorization" in mock_http.get.call_args[1]["headers"]


# ── 9. Refresh-token encryption ───────────────────────────────────────────────

def test_refresh_token_encryption():
    """Verify AES-256-GCM authenticated encryption produces non-plaintext cipher."""
    service = TokenEncryptionService(key="test_encryption_key_32_bytes_long_secret!")
    plaintext_token = "1//04my_precious_refresh_token_9999"

    ciphertext = service.encrypt(plaintext_token)

    assert ciphertext is not None
    assert plaintext_token not in ciphertext
    assert isinstance(ciphertext, str)
    assert len(ciphertext) > 30


# ── 10. Refresh-token decryption ──────────────────────────────────────────────

def test_refresh_token_decryption_and_tamper_detection():
    """Verify decryption restores original token and tampering raises error."""
    service = TokenEncryptionService(key="test_encryption_key_32_bytes_long_secret!")
    plaintext_token = "1//04my_precious_refresh_token_9999"

    ciphertext = service.encrypt(plaintext_token)
    decrypted = service.decrypt(ciphertext)
    assert decrypted == plaintext_token

    # Tamper with the ciphertext
    tampered_bytes = bytearray(ciphertext.encode("ascii"))
    tampered_bytes[-2] = ord("A") if tampered_bytes[-2] != ord("A") else ord("B")
    tampered_ciphertext = tampered_bytes.decode("ascii")

    with pytest.raises(TokenDecryptionError):
        service.decrypt(tampered_ciphertext)


# ── 11. Missing encryption key -> Fail Closed ──────────────────────────────────

def test_missing_encryption_key_fails_closed():
    """When encryption key is missing or blank, system must fail closed."""
    service = TokenEncryptionService(key="")
    with pytest.raises(TokenEncryptionKeyMissingError):
        service.encrypt("test_token")

    with pytest.raises(TokenEncryptionKeyMissingError):
        service.decrypt("some_ciphertext")


# ── 12. Token never appears in API response ───────────────────────────────────

@pytest.mark.asyncio
async def test_token_never_appears_in_api_response(client: AsyncClient, auth_headers: dict):
    """Verify refresh and access tokens NEVER appear in API responses."""
    secret_refresh = "1//04SECRET_REFRESH_TOKEN_DO_NOT_LEAK"
    secret_access = "ya29.SECRET_ACCESS_TOKEN_DO_NOT_LEAK"

    # 1. Connect
    connect_res = await client.get("/api/v1/gmail/connect", headers=auth_headers)
    assert connect_res.status_code == 200
    state = connect_res.json()["state"]
    assert "token" not in connect_res.text

    # 2. Callback with mocks
    mock_post_resp = Response(
        status_code=200,
        json={"access_token": secret_access, "refresh_token": secret_refresh},
    )
    mock_get_resp = Response(
        status_code=200,
        json={"email": "owner@agency.com"},
    )

    with mock_google_service_http(post_response=mock_post_resp, get_response=mock_get_resp):
        callback_res = await client.get(
            f"/api/v1/gmail/callback?code=mock_code&state={state}",
            headers=auth_headers,
        )
        assert callback_res.status_code == 200
        assert secret_refresh not in callback_res.text
        assert secret_access not in callback_res.text

    # 3. Status endpoint
    status_res = await client.get("/api/v1/gmail/status", headers=auth_headers)
    assert status_res.status_code == 200
    assert secret_refresh not in status_res.text
    assert secret_access not in status_res.text

    # 4. Disconnect endpoint
    with mock_google_service_http(post_response=Response(status_code=200)):
        disconnect_res = await client.post("/api/v1/gmail/disconnect", headers=auth_headers)
        assert disconnect_res.status_code == 200
        assert secret_refresh not in disconnect_res.text
        assert secret_access not in disconnect_res.text


# ── 13. Token never appears in logs or audit entries ──────────────────────────

@pytest.mark.asyncio
async def test_token_never_appears_in_logs_or_audit(
    client: AsyncClient, auth_headers: dict, caplog: pytest.LogCaptureFixture
):
    """Tokens must NEVER appear in application logs or AgentRun database records."""
    caplog.set_level(logging.DEBUG)
    secret_refresh = "1//04SUPER_CONFIDENTIAL_TOKEN_XYZ"
    secret_access = "ya29.SUPER_CONFIDENTIAL_ACCESS_ABC"

    # Connect
    connect_res = await client.get("/api/v1/gmail/connect", headers=auth_headers)
    state = connect_res.json()["state"]

    mock_post_resp = Response(
        status_code=200,
        json={"access_token": secret_access, "refresh_token": secret_refresh},
    )
    mock_get_resp = Response(
        status_code=200,
        json={"email": "owner@agency.com"},
    )

    with mock_google_service_http(post_response=mock_post_resp, get_response=mock_get_resp):
        cb_res = await client.get(
            f"/api/v1/gmail/callback?code=code_123&state={state}",
            headers=auth_headers,
        )
        assert cb_res.status_code == 200

    # Check logs
    assert secret_refresh not in caplog.text
    assert secret_access not in caplog.text

    # Check database audit records in agent_runs
    async with TestSessionLocal() as session:
        runs = (await session.scalars(select(AgentRun).where(AgentRun.agent_name == "gmail_oauth"))).all()
        assert len(runs) >= 2
        for r in runs:
            data_str = str(r.input_data) + str(r.output_data)
            assert secret_refresh not in data_str
            assert secret_access not in data_str


# ── 14. Gmail status (CONNECTED) ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gmail_status_connected(client: AsyncClient, auth_headers: dict):
    """GET /api/v1/gmail/status returns CONNECTED status with safe metadata and minimal scopes."""
    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="connected_owner@gmail.com",
            encrypted_refresh_token="mock_encrypted_token",
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
    assert data["email"] == "connected_owner@gmail.com"
    assert data["connection_status"] == "CONNECTED"
    assert data["scopes"] == SAFE_SCOPE_LABELS
    assert "gmail.send" in data["scopes"]
    assert "gmail.readonly" not in str(data["scopes"])


# ── 15. Gmail disconnected status ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gmail_disconnected_status(client: AsyncClient, auth_headers: dict):
    """GET /api/v1/gmail/status returns DISCONNECTED when no account is connected."""
    response = await client.get("/api/v1/gmail/status", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert data["connection_status"] == "DISCONNECTED"
    assert data["email"] is None
    assert data["scopes"] == []


# ── 16. Gmail health failure ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gmail_health_failure(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/gmail/health-check marks connection DISCONNECTED when Google rejects token."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("valid_looking_token_123")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="test@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
        )
        session.add(account)
        await session.commit()

    mock_resp = Response(
        status_code=401,
        json={"error": "invalid_grant", "error_description": "Token has been revoked."},
    )

    with mock_google_service_http(post_response=mock_resp):
        response = await client.post("/api/v1/gmail/health-check", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_healthy"] is False
        assert data["status"] in ("DISCONNECTED", "UNHEALTHY")

    async with TestSessionLocal() as session:
        audit_run = await session.scalar(
            select(AgentRun)
            .where(AgentRun.agent_name == "gmail_oauth")
            .where(AgentRun.input_data["action"].as_string() == "gmail_health_failure")
        )
        assert audit_run is not None
        assert audit_run.status == AgentRunStatus.FAILED


# ── 17. Disconnect ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_disconnect_invalidates_credentials_and_audits(client: AsyncClient, auth_headers: dict):
    """POST /api/v1/gmail/disconnect purges stored credentials and marks account DISCONNECTED."""
    encryption_service = TokenEncryptionService()
    encrypted_token = encryption_service.encrypt("active_refresh_token")

    async with TestSessionLocal() as session:
        account = GmailAccount(
            owner_id="test@example.com",
            google_email="to_disconnect@gmail.com",
            encrypted_refresh_token=encrypted_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=datetime.now(timezone.utc),
        )
        session.add(account)
        await session.commit()

    with mock_google_service_http(post_response=Response(status_code=200)):
        response = await client.post("/api/v1/gmail/disconnect", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "DISCONNECTED"

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


# ── 18. IDOR protection across all endpoints ──────────────────────────────────

@pytest.mark.asyncio
async def test_idor_protection_across_all_gmail_endpoints(client: AsyncClient):
    """Imposter owner must be rejected with 403 Forbidden across all Gmail endpoints."""
    imposter_token, _ = _create_access_token("attacker@badactor.com")
    headers = {"Authorization": f"Bearer {imposter_token}"}

    res = await client.get("/api/v1/gmail/connect", headers=headers)
    assert res.status_code == 403

    res = await client.get("/api/v1/gmail/status", headers=headers)
    assert res.status_code == 403

    res = await client.post("/api/v1/gmail/disconnect", headers=headers)
    assert res.status_code == 403

    res = await client.post("/api/v1/gmail/health-check", headers=headers)
    assert res.status_code == 403


# ── 19. OAuth callback failure scenarios ──────────────────────────────────────

@pytest.mark.asyncio
async def test_oauth_callback_failures(client: AsyncClient, auth_headers: dict):
    """Verify robust error handling and failure audit logs across various callback failure modes."""
    # 1. Google error returned
    res = await client.get("/api/v1/gmail/callback?error=access_denied", headers=auth_headers)
    assert res.status_code == 400
    assert "Google OAuth authorization failed" in res.json().get("detail", "")

    # 2. Missing state
    res = await client.get("/api/v1/gmail/callback?code=abc", headers=auth_headers)
    assert res.status_code == 400
    assert "Missing required OAuth state parameter" in res.json().get("detail", "")

    # 3. Invalid state
    res = await client.get("/api/v1/gmail/callback?code=abc&state=bad_state", headers=auth_headers)
    assert res.status_code == 400

    # 4. State valid but missing code
    service = GmailOAuthService()
    valid_state = service.generate_state("test@example.com")
    res = await client.get(f"/api/v1/gmail/callback?state={valid_state}", headers=auth_headers)
    assert res.status_code == 400
    assert "Missing authorization code" in res.json().get("detail", "")

    # 5. Google token exchange network error
    with mock_google_service_http(post_response=Response(status_code=500, text="Internal Google Server Error")):
        res = await client.get(
            f"/api/v1/gmail/callback?code=code_123&state={valid_state}",
            headers=auth_headers,
        )
        assert res.status_code == 400
        assert "Failed to exchange authorization code" in res.json().get("detail", "")


# ── 20. End-to-end mocked OAuth flow ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_mocked_oauth_connection_flow(client: AsyncClient, auth_headers: dict):
    """
    Complete end-to-end OAuth flow:
    Connect -> Authorization URL -> Callback -> Decryptable Token -> Status CONNECTED
    """
    # 1. Connect
    connect_res = await client.get("/api/v1/gmail/connect", headers=auth_headers)
    assert connect_res.status_code == 200
    connect_data = connect_res.json()
    auth_url = connect_data["authorization_url"]
    state = connect_data["state"]

    assert "accounts.google.com/o/oauth2/v2/auth" in auth_url
    assert "scope=" in auth_url
    assert "gmail.send" in auth_url
    # Ensure no forbidden scopes
    assert "gmail.readonly" not in auth_url
    assert "gmail.modify" not in auth_url
    assert "gmail.compose" not in auth_url

    # 2. Callback
    mock_post_resp = Response(
        status_code=200,
        json={
            "access_token": "ya29.mock_final_access_token",
            "refresh_token": "1//04mock_final_refresh_token",
            "expires_in": 3600,
        },
    )
    mock_get_resp = Response(
        status_code=200,
        json={"email": "verified.agency.owner@gmail.com"},
    )

    with mock_google_service_http(post_response=mock_post_resp, get_response=mock_get_resp):
        callback_res = await client.get(
            f"/api/v1/gmail/callback?code=google_auth_code_999&state={state}",
            headers=auth_headers,
        )
        assert callback_res.status_code == 200
        status_data = callback_res.json()
        assert status_data["connected"] is True
        assert status_data["email"] == "verified.agency.owner@gmail.com"
        assert status_data["connection_status"] == "CONNECTED"

    # 3. Verify in database: token is encrypted, not plaintext
    async with TestSessionLocal() as session:
        account = await session.scalar(select(GmailAccount).where(GmailAccount.owner_id == "test@example.com"))
        assert account is not None
        assert account.google_email == "verified.agency.owner@gmail.com"
        assert account.connection_status == GmailConnectionStatus.CONNECTED
        assert "1//04mock_final_refresh_token" not in account.encrypted_refresh_token

        # Verify decryption restores exact token
        encryption_service = TokenEncryptionService()
        decrypted = encryption_service.decrypt(account.encrypted_refresh_token)
        assert decrypted == "1//04mock_final_refresh_token"
