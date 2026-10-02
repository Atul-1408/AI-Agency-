"""
Gmail Credential & Token Refresh Service.

Provides a clean abstraction for:
- Decrypting stored refresh tokens (fail closed)
- Refreshing Google OAuth access tokens internally
- Classifying Google OAuth response codes and errors
- Never logging or exposing access/refresh tokens
- Determining operational connection status (CONNECTED, DISCONNECTED, ERROR)

SECURITY MANDATE:
- Access tokens and refresh tokens remain strictly internal to this service.
- Never persist access tokens unless demonstrated.
- Never log token values or secrets.
- Accurately distinguish temporary infrastructure faults (ERROR) from permanent
  credential revocations (DISCONNECTED).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import httpx
import structlog

from core.config import settings
from models.outreach import GmailAccount, GmailConnectionStatus
from services.token_encryption import (
    TokenDecryptionError,
    TokenEncryptionKeyMissingError,
    TokenEncryptionService,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class HealthAssessmentResult:
    """Outcome of a non-intrusive Gmail credential verification."""
    status: GmailConnectionStatus
    is_healthy: bool
    error_code: Optional[str] = None
    error_detail: Optional[str] = None


class GmailCredentialService:
    """
    Manages OAuth credential health and token refreshes without persistence
    of plaintext secrets.
    """

    def __init__(self, encryption_service: Optional[TokenEncryptionService] = None):
        self._encryption_service = encryption_service or TokenEncryptionService()

    async def verify_credential_health(self, account: GmailAccount) -> HealthAssessmentResult:
        """
        Validate Gmail account credential health by attempting a minimal token refresh.
        Classifies response without sending email or accessing inbox data.
        """
        # 1. State check
        if account.connection_status == GmailConnectionStatus.DISCONNECTED:
            return HealthAssessmentResult(
                status=GmailConnectionStatus.DISCONNECTED,
                is_healthy=False,
                error_code="ACCOUNT_DISCONNECTED",
                error_detail="Gmail account is marked as disconnected.",
            )

        if not account.encrypted_refresh_token or not account.encrypted_refresh_token.strip():
            return HealthAssessmentResult(
                status=GmailConnectionStatus.DISCONNECTED,
                is_healthy=False,
                error_code="TOKEN_MISSING",
                error_detail="No refresh token credential stored for account.",
            )

        # 2. Decrypt refresh token
        try:
            refresh_token = self._encryption_service.decrypt(account.encrypted_refresh_token)
        except TokenEncryptionKeyMissingError as exc:
            log.error("Token encryption key missing during credential health check (Failing Closed)")
            return HealthAssessmentResult(
                status=GmailConnectionStatus.ERROR,
                is_healthy=False,
                error_code="KEY_MISSING",
                error_detail="Server encryption key is not configured.",
            )
        except TokenDecryptionError as exc:
            log.warning("Token decryption failed: corrupted ciphertext or wrong key")
            return HealthAssessmentResult(
                status=GmailConnectionStatus.ERROR,
                is_healthy=False,
                error_code="DECRYPTION_FAILED",
                error_detail="Failed to decrypt token: payload corrupted or key mismatch.",
            )
        except Exception as exc:
            log.warning("Unexpected error decrypting refresh token", error=str(exc))
            return HealthAssessmentResult(
                status=GmailConnectionStatus.ERROR,
                is_healthy=False,
                error_code="DECRYPTION_FAILED",
                error_detail="Unexpected decryption error.",
            )

        if not refresh_token or not refresh_token.strip():
            return HealthAssessmentResult(
                status=GmailConnectionStatus.DISCONNECTED,
                is_healthy=False,
                error_code="TOKEN_EMPTY",
                error_detail="Decrypted refresh token was empty.",
            )

        # 3. Check configuration
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            log.warning("Google OAuth client configuration missing during health check")
            return HealthAssessmentResult(
                status=GmailConnectionStatus.ERROR,
                is_healthy=False,
                error_code="CONFIG_MISSING",
                error_detail="Google OAuth client ID or secret is not configured.",
            )

        # 4. Attempt Google OAuth token refresh
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
        except httpx.TimeoutException:
            log.warning("Timeout communicating with Google OAuth server during health check")
            return HealthAssessmentResult(
                status=GmailConnectionStatus.ERROR,
                is_healthy=False,
                error_code="TIMEOUT",
                error_detail="Google OAuth server request timed out.",
            )
        except (httpx.NetworkError, httpx.ConnectError) as exc:
            log.warning("Network connection failure during health check", error=str(exc))
            return HealthAssessmentResult(
                status=GmailConnectionStatus.ERROR,
                is_healthy=False,
                error_code="NETWORK_ERROR",
                error_detail="Network connection error communicating with Google.",
            )
        except Exception as exc:
            log.warning("Unexpected error during Google health request", error=str(exc))
            return HealthAssessmentResult(
                status=GmailConnectionStatus.ERROR,
                is_healthy=False,
                error_code="NETWORK_ERROR",
                error_detail="Failed to connect to Google OAuth service.",
            )

        # 5. Classify HTTP Response
        return self._classify_google_response(response)

    def _classify_google_response(self, response: httpx.Response) -> HealthAssessmentResult:
        """
        Classifies Google OAuth token refresh HTTP response codes into
        permanent revocations vs temporary errors vs success.
        """
        status_code = response.status_code

        # HTTP 200: Success
        if status_code == 200:
            try:
                data = response.json()
            except Exception:
                return HealthAssessmentResult(
                    status=GmailConnectionStatus.ERROR,
                    is_healthy=False,
                    error_code="MALFORMED_RESPONSE",
                    error_detail="Google returned non-JSON response.",
                )

            access_token = data.get("access_token")
            if not access_token:
                return HealthAssessmentResult(
                    status=GmailConnectionStatus.ERROR,
                    is_healthy=False,
                    error_code="MALFORMED_RESPONSE",
                    error_detail="Google token response missing access_token.",
                )

            return HealthAssessmentResult(
                status=GmailConnectionStatus.CONNECTED,
                is_healthy=True,
                error_code=None,
                error_detail="Token refresh verified successfully.",
            )

        # HTTP 400: invalid_grant / revoked credential
        if status_code == 400:
            try:
                data = response.json()
                err = str(data.get("error", ""))
                err_desc = str(data.get("error_description", ""))
            except Exception:
                err = ""
                err_desc = ""

            if "invalid_grant" in err.lower() or "invalid_grant" in err_desc.lower():
                log.warning("Google reported invalid_grant (revoked or expired refresh token)")
                return HealthAssessmentResult(
                    status=GmailConnectionStatus.DISCONNECTED,
                    is_healthy=False,
                    error_code="INVALID_GRANT",
                    error_detail=f"Google rejected credential: {err_desc or err}",
                )

            return HealthAssessmentResult(
                status=GmailConnectionStatus.DISCONNECTED,
                is_healthy=False,
                error_code="INVALID_REQUEST",
                error_detail=f"OAuth error 400: {err_desc or err}",
            )

        # HTTP 401: Authentication failure (bad client credentials or revoked)
        if status_code == 401:
            log.warning("Google returned 401 Unauthorized for client credentials")
            return HealthAssessmentResult(
                status=GmailConnectionStatus.DISCONNECTED,
                is_healthy=False,
                error_code="UNAUTHORIZED",
                error_detail="Google returned 401 Unauthorized for OAuth credentials.",
            )

        # HTTP 403: Forbidden (account blocked, permission revoked)
        if status_code == 403:
            log.warning("Google returned 403 Forbidden for account")
            return HealthAssessmentResult(
                status=GmailConnectionStatus.DISCONNECTED,
                is_healthy=False,
                error_code="FORBIDDEN",
                error_detail="Google returned 403 Forbidden for account.",
            )

        # HTTP 429: Rate limit (temporary) -> ERROR
        if status_code == 429:
            log.warning("Google OAuth token endpoint rate limited (429)")
            return HealthAssessmentResult(
                status=GmailConnectionStatus.ERROR,
                is_healthy=False,
                error_code="RATE_LIMITED",
                error_detail="Google OAuth rate limit exceeded. Retry later.",
            )

        # HTTP 5xx: Google infrastructure failure (temporary) -> ERROR
        if status_code >= 500:
            log.warning("Google server error during token refresh", status_code=status_code)
            return HealthAssessmentResult(
                status=GmailConnectionStatus.ERROR,
                is_healthy=False,
                error_code="GOOGLE_5XX",
                error_detail=f"Google OAuth server error ({status_code}).",
            )

        # Unhandled status code -> ERROR
        return HealthAssessmentResult(
            status=GmailConnectionStatus.ERROR,
            is_healthy=False,
            error_code=f"HTTP_{status_code}",
            error_detail=f"Unexpected HTTP {status_code} from Google OAuth server.",
        )
