"""
Gmail Dispatch Service.

Implements the controlled single-email manual dispatch adapter for Phase 4 Stage 4.3.

RESPONSIBILITIES:
- Encapsulates Google Gmail API message dispatch: POST /gmail/v1/users/me/messages/send
- Obtains ephemeral access token from GmailCredentialService (never persisted or logged)
- Constructs standard RFC 2822 / MIME plain text message from approved OutreachDraft
- Sends exactly ONE message per invocation
- Returns Google-assigned Message ID and Thread ID
- Classifies Gmail API error responses accurately
- Fails closed on any infrastructure or credential error
- Strictly NO batch sending, NO automatic sending, NO scheduled sending, NO inbox reading
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional

import httpx
import structlog

from models.outreach import GmailAccount, OutreachDraft
from services.gmail_credential_service import CredentialRefreshError, GmailCredentialService
from services.token_encryption import TokenEncryptionService

log = structlog.get_logger(__name__)


class GmailDispatchError(Exception):
    """Base exception for all Gmail API dispatch failures."""
    pass


class GmailDispatchAuthError(GmailDispatchError):
    """Authentication or token credential failure (401)."""
    pass


class GmailDispatchPermissionError(GmailDispatchError):
    """Insufficient scope or permission error (403)."""
    pass


class GmailDispatchRateLimitError(GmailDispatchError):
    """Google Gmail API rate limit hit (429)."""
    pass


class GmailDispatchInvalidRequestError(GmailDispatchError):
    """Malformed or invalid request rejected by Google (400)."""
    pass


class GmailDispatchServerError(GmailDispatchError):
    """Google Gmail server-side outage or 5xx error."""
    pass


class GmailDispatchTimeoutError(GmailDispatchError):
    """Network timeout communicating with Gmail API."""
    pass


class GmailDispatchNetworkError(GmailDispatchError):
    """Network connection failure communicating with Gmail API."""
    pass


@dataclass(frozen=True)
class GmailDispatchResult:
    """Safe result containing Google message identifiers and dispatch metadata."""
    gmail_message_id: str
    gmail_thread_id: str
    sent_at: datetime
    recipient_email: str
    subject: str


class GmailDispatchService:
    """
    Dedicated dispatch adapter for delivering exactly one approved OutreachDraft
    via the Google Gmail API.
    """

    def __init__(
        self,
        credential_service: Optional[GmailCredentialService] = None,
        encryption_service: Optional[TokenEncryptionService] = None,
    ):
        self._credential_service = credential_service or GmailCredentialService(
            encryption_service=encryption_service
        )

    def build_mime_message(
        self,
        recipient_email: str,
        sender_email: str,
        subject: str,
        body_text: str,
    ) -> str:
        """
        Construct an RFC 2822 compliant MIME message in PLAIN TEXT format.
        Encodes the message using URL-safe Base64 as required by the Gmail API.
        """
        if not recipient_email or not recipient_email.strip():
            raise GmailDispatchInvalidRequestError("Recipient email is required.")
        if not sender_email or not sender_email.strip():
            raise GmailDispatchInvalidRequestError("Sender email is required.")

        msg = EmailMessage()
        msg["To"] = recipient_email.strip()
        msg["From"] = sender_email.strip()
        msg["Subject"] = subject or "(No Subject)"
        msg.set_content(body_text or "")

        raw_bytes = msg.as_bytes()
        return base64.urlsafe_b64encode(raw_bytes).decode("ascii")

    async def dispatch_draft(
        self,
        account: GmailAccount,
        draft: OutreachDraft,
    ) -> GmailDispatchResult:
        """
        Send exactly one email message via Google Gmail API.
        Never retries automatically.
        """
        # 1. Obtain fresh access token
        try:
            access_token = await self._credential_service.get_access_token(account)
        except CredentialRefreshError as exc:
            log.warning("Failed to acquire access token for dispatch", error=str(exc))
            raise GmailDispatchAuthError(f"Credential authentication failed: {str(exc)}") from exc

        # 2. Build plain text MIME message from approved draft data
        raw_payload = self.build_mime_message(
            recipient_email=draft.recipient_email,
            sender_email=account.google_email,
            subject=draft.subject,
            body_text=draft.body_text or "",
        )

        # 3. Dispatch to Gmail API
        gmail_send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        body = {"raw": raw_payload}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(gmail_send_url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            log.warning("Timeout during Gmail API send", draft_id=str(draft.id))
            raise GmailDispatchTimeoutError("Gmail API timed out while sending message.") from exc
        except (httpx.NetworkError, httpx.ConnectError) as exc:
            log.warning("Network connection failure during Gmail API send", draft_id=str(draft.id), error=str(exc))
            raise GmailDispatchNetworkError("Network error connecting to Gmail API.") from exc
        except Exception as exc:
            log.warning("Unexpected network failure during send", draft_id=str(draft.id), error=str(exc))
            raise GmailDispatchNetworkError(f"Unexpected network failure during send: {str(exc)}") from exc

        # 4. Handle and classify response
        status_code = response.status_code

        if status_code == 200:
            try:
                data = response.json()
            except Exception as exc:
                raise GmailDispatchServerError("Malformed response from Gmail API after send.") from exc

            message_id = data.get("id")
            thread_id = data.get("threadId", message_id)
            if not message_id:
                raise GmailDispatchServerError("Gmail API response missing message id.")

            now = datetime.now(timezone.utc)
            return GmailDispatchResult(
                gmail_message_id=message_id,
                gmail_thread_id=thread_id,
                sent_at=now,
                recipient_email=draft.recipient_email,
                subject=draft.subject,
            )

        # Classify Google errors
        if status_code == 401:
            log.warning("Gmail API rejected access token (401)")
            raise GmailDispatchAuthError("Gmail API rejected access token (401 Unauthorized).")
        elif status_code == 403:
            log.warning("Gmail API returned 403 Forbidden")
            raise GmailDispatchPermissionError("Gmail API returned 403 Forbidden. Check scope permissions.")
        elif status_code == 429:
            log.warning("Gmail API rate limit exceeded (429)")
            raise GmailDispatchRateLimitError("Gmail API rate limit exceeded (429).")
        elif status_code == 400:
            log.warning("Gmail API rejected request format (400)")
            raise GmailDispatchInvalidRequestError("Gmail API rejected message payload (400 Bad Request).")
        elif status_code >= 500:
            log.warning("Google Gmail API server error", status_code=status_code)
            raise GmailDispatchServerError(f"Google Gmail server error (HTTP {status_code}).")
        else:
            raise GmailDispatchError(f"Unexpected Gmail API error (HTTP {status_code}).")
