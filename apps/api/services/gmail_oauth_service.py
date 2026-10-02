"""
Gmail OAuth & Connection Service.

Handles:
- Google OAuth 2.0 authorization URL creation with cryptographically secure state
- State token issuance and owner-bound CSRF validation
- Authorization code exchange for tokens (strictly mocked during tests)
- User identity verification
- Refresh token authenticated encryption
- Gmail connection health assessment (without sending or inbox reading)
- Token revocation and disconnect handling

SECURITY MANDATES:
1. ONLY minimum required OAuth scopes:
   - https://www.googleapis.com/auth/gmail.send
   - openid
   - email
2. STRICTLY FORBIDDEN:
   - gmail.readonly
   - gmail.modify
   - gmail.compose
   - gmail.metadata
   No inbox-reading permissions.
3. Refresh tokens are NEVER logged, exposed in API responses, or stored in plaintext.
4. Fails closed if configuration (client ID, secret, encryption key) is missing.
"""
from __future__ import annotations

import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from jose import ExpiredSignatureError, JWTError, jwt
import structlog

from core.config import settings
from models.outreach import GmailAccount, GmailConnectionStatus
from services.token_encryption import TokenEncryptionKeyMissingError, TokenEncryptionService

log = structlog.get_logger(__name__)

# Minimum required OAuth scopes ONLY
MINIMUM_OAUTH_SCOPES: List[str] = [
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "email",
]

# Scope display labels for client status
SAFE_SCOPE_LABELS: List[str] = [
    "gmail.send",
    "openid",
    "email",
]


class GmailOAuthError(Exception):
    """Base exception for Gmail OAuth failures."""
    pass


class GmailOAuthConfigError(GmailOAuthError):
    """Raised when OAuth credentials or encryption settings are unconfigured."""
    pass


class OAuthStateInvalidError(GmailOAuthError):
    """Raised when OAuth state token is missing, expired, tampered, or mismatched."""
    pass


class OAuthExchangeError(GmailOAuthError):
    """Raised when authorization code exchange or identity retrieval fails."""
    pass


class GmailHealthCheckError(GmailOAuthError):
    """Raised when health check encounters an unexpected internal failure."""
    pass


class GmailOAuthService:
    """
    Service coordinating secure Google OAuth 2.0 lifecycle and account health.
    """

    def __init__(self, encryption_service: Optional[TokenEncryptionService] = None):
        self._encryption_service = encryption_service or TokenEncryptionService()

    def validate_configuration(self) -> None:
        """
        Verify that all required OAuth settings and encryption keys are present.
        Fails closed immediately if any required setting is missing.
        """
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_ID.strip():
            raise GmailOAuthConfigError("GOOGLE_CLIENT_ID is not configured. OAuth cannot start.")
        if not settings.GOOGLE_CLIENT_SECRET or not settings.GOOGLE_CLIENT_SECRET.strip():
            raise GmailOAuthConfigError("GOOGLE_CLIENT_SECRET is not configured. OAuth cannot start.")
        if not settings.GOOGLE_REDIRECT_URI or not settings.GOOGLE_REDIRECT_URI.strip():
            raise GmailOAuthConfigError("GOOGLE_REDIRECT_URI is not configured. OAuth cannot start.")
        if not settings.GMAIL_TOKEN_ENCRYPTION_KEY or not settings.GMAIL_TOKEN_ENCRYPTION_KEY.strip():
            raise GmailOAuthConfigError("GMAIL_TOKEN_ENCRYPTION_KEY is not configured. OAuth cannot start.")

    def generate_state(self, owner_email: str) -> str:
        """
        Generate a cryptographically random, owner-bound, expiring OAuth state token.
        Uses JWT signed with APP_SECRET with a 10-minute TTL.
        """
        if not owner_email or not owner_email.strip():
            raise OAuthStateInvalidError("Owner email required to generate bound OAuth state.")

        now = datetime.now(timezone.utc)
        payload = {
            "sub": owner_email.strip().lower(),
            "nonce": secrets.token_urlsafe(16),
            "purpose": "gmail_oauth_state",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=10)).timestamp()),
        }
        return jwt.encode(payload, settings.APP_SECRET, algorithm="HS256")

    def validate_state(self, state: str, expected_owner_email: Optional[str] = None) -> str:
        """
        Validate state token integrity, expiration, purpose, and owner binding.
        Returns the bound owner email from the verified state claims.
        """
        if not state or not state.strip():
            raise OAuthStateInvalidError("Missing OAuth state parameter.")

        try:
            payload = jwt.decode(
                state.strip(),
                settings.APP_SECRET,
                algorithms=["HS256"],
                options={"require_exp": True},
            )
        except ExpiredSignatureError as exc:
            raise OAuthStateInvalidError("OAuth state has expired. Please initiate connection again.") from exc
        except JWTError as exc:
            raise OAuthStateInvalidError("Invalid or tampered OAuth state parameter.") from exc

        if payload.get("purpose") != "gmail_oauth_state":
            raise OAuthStateInvalidError("Invalid OAuth state purpose token.")

        state_owner = payload.get("sub")
        if not state_owner:
            raise OAuthStateInvalidError("OAuth state is missing owner binding claim.")

        if expected_owner_email:
            normalized_expected = expected_owner_email.strip().lower()
            if state_owner.strip().lower() != normalized_expected:
                raise OAuthStateInvalidError(
                    "OAuth state owner mismatch: state was not issued to the authenticated owner."
                )

        return state_owner

    def get_authorization_url(self, owner_email: str) -> Dict[str, str]:
        """
        Build the Google OAuth 2.0 authorization URL with minimum required scopes.
        Fails closed if configuration is missing.
        """
        self.validate_configuration()
        state = self.generate_state(owner_email)

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(MINIMUM_OAUTH_SCOPES),
            "access_type": "offline",
            "prompt": "consent",  # Force consent to ensure refresh token is returned
            "state": state,
        }
        query_string = urllib.parse.urlencode(params)
        auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{query_string}"
        return {"authorization_url": auth_url, "state": state}

    async def exchange_code_for_tokens(self, code: str) -> Dict[str, Any]:
        """
        Exchange an authorization code for tokens with Google's token endpoint.
        Returns the parsed token response dictionary.
        Does not log secrets or tokens.
        """
        self.validate_configuration()

        if not code or not code.strip():
            raise OAuthExchangeError("Authorization code cannot be empty.")

        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "code": code.strip(),
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(token_url, data=payload)
                if response.status_code != 200:
                    log.warning("Google OAuth token exchange rejected", status_code=response.status_code)
                    raise OAuthExchangeError(
                        f"Google rejected authorization code exchange (HTTP {response.status_code})."
                    )
                return response.json()
        except OAuthExchangeError:
            raise
        except Exception as exc:
            log.warning("Network or provider error during OAuth token exchange", error=str(exc))
            raise OAuthExchangeError("Unable to communicate with Google OAuth server.") from exc

    async def get_user_identity(self, access_token: str) -> str:
        """
        Retrieve the verified Google email address associated with the access token.
        Does not log the access token.
        """
        if not access_token or not access_token.strip():
            raise OAuthExchangeError("Access token is required to retrieve Google identity.")

        userinfo_url = "https://www.googleapis.com/oauth2/v2/userinfo"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    userinfo_url,
                    headers={"Authorization": f"Bearer {access_token.strip()}"},
                )
                if response.status_code != 200:
                    log.warning("Google userinfo request rejected", status_code=response.status_code)
                    raise OAuthExchangeError("Failed to retrieve user profile from Google.")
                data = response.json()
                email = data.get("email")
                if not email or not email.strip():
                    raise OAuthExchangeError("Google identity response missing email field.")
                return email.strip().lower()
        except OAuthExchangeError:
            raise
        except Exception as exc:
            log.warning("Network error retrieving Google user identity", error=str(exc))
            raise OAuthExchangeError("Failed to retrieve Google user identity.") from exc

    async def revoke_token(self, token: str) -> bool:
        """
        Revoke an access or refresh token with Google's revocation endpoint.
        Gracefully handles network errors.
        """
        if not token or not token.strip():
            return False

        revoke_url = "https://oauth2.googleapis.com/revoke"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(revoke_url, params={"token": token.strip()})
                return response.status_code == 200
        except Exception as exc:
            log.warning("Error revoking token with Google", error=str(exc))
            return False

    async def check_account_health(self, account: GmailAccount) -> GmailConnectionStatus:
        """
        Perform a non-intrusive health assessment of the stored Gmail account.
        Checks:
        1. Encryption key configuration and token decryption integrity.
        2. Refresh token presence.
        3. Token validity check via token refresh against Google's OAuth endpoint.
        
        DOES NOT:
        - Send any email
        - Create any Gmail messages
        - Read inbox or access messages
        """
        if account.connection_status == GmailConnectionStatus.DISCONNECTED:
            return GmailConnectionStatus.DISCONNECTED

        if not account.encrypted_refresh_token or not account.encrypted_refresh_token.strip():
            return GmailConnectionStatus.DISCONNECTED

        # 1. Decrypt token
        try:
            refresh_token = self._encryption_service.decrypt(account.encrypted_refresh_token)
        except TokenEncryptionKeyMissingError:
            log.error("Token encryption key missing during health check. Marking ERROR.")
            return GmailConnectionStatus.ERROR
        except Exception as exc:
            log.warning("Decryption failed during health check. Token corrupted or wrong key.", error=str(exc))
            return GmailConnectionStatus.ERROR

        if not refresh_token or not refresh_token.strip():
            return GmailConnectionStatus.DISCONNECTED

        # 2. Check token refresh validity with Google OAuth server
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            log.warning("OAuth client configuration missing during health check.")
            return GmailConnectionStatus.ERROR

        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(token_url, data=payload)
                if response.status_code == 200:
                    return GmailConnectionStatus.CONNECTED
                elif response.status_code in (400, 401):
                    # Google rejected refresh token (e.g. revoked, expired)
                    log.warning("Google rejected refresh token during health check", status=response.status_code)
                    return GmailConnectionStatus.DISCONNECTED
                else:
                    log.warning("Unexpected status from Google during health check", status=response.status_code)
                    return GmailConnectionStatus.ERROR
        except Exception as exc:
            log.warning("Network failure during Gmail health check", error=str(exc))
            return GmailConnectionStatus.ERROR
