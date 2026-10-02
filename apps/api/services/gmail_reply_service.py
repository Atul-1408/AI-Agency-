"""
Gmail Reply Service.

Adapter for inspecting Gmail thread and message metadata for prospect replies.

RESPONSIBILITIES:
- Encapsulates Google Gmail API thread metadata fetching: GET /gmail/v1/users/me/threads/{id}?format=metadata
- Obtains ephemeral access token from GmailCredentialService (never persisted or logged)
- Restricts payload fetching strictly to metadata (NO full email body downloaded)
- Parses sender, recipient, date, subject, in-reply-to, and references headers safely
- Treats all incoming header values and snippets as UNTRUSTED DATA
- Classifies Gmail API error responses accurately (401, 403, 429, 5xx, timeout, network error)
- Fails closed on any credential, scope, or infrastructure error
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import email.utils
import re
from typing import Any, Dict, List, Optional

import httpx
import structlog

from models.outreach import GmailAccount
from services.gmail_credential_service import CredentialRefreshError, GmailCredentialService
from services.token_encryption import TokenEncryptionService

log = structlog.get_logger(__name__)


class GmailReplyError(Exception):
    """Base exception for all Gmail API reply detection failures."""
    pass


class GmailReplyAuthError(GmailReplyError):
    """Authentication or token credential failure (401)."""
    pass


class GmailReplyPermissionError(GmailReplyError):
    """Insufficient scope or permission error (403)."""
    pass


class GmailReplyRateLimitError(GmailReplyError):
    """Google Gmail API rate limit hit (429)."""
    pass


class GmailReplyServerError(GmailReplyError):
    """Google Gmail server-side outage or 5xx error."""
    pass


class GmailReplyTimeoutError(GmailReplyError):
    """Network timeout communicating with Gmail API."""
    pass


class GmailReplyNetworkError(GmailReplyError):
    """Network connection failure communicating with Gmail API."""
    pass


class GmailReplyMalformedError(GmailReplyError):
    """Malformed or invalid JSON response from Google Gmail API."""
    pass


@dataclass(frozen=True)
class InboundMessageMetadata:
    """Safe representation of parsed Gmail message metadata."""
    message_id: str
    thread_id: str
    sender_email: str
    recipient_email: str
    subject: Optional[str]
    snippet: Optional[str]
    received_at: datetime
    in_reply_to: Optional[str] = None
    references: Optional[str] = None


def extract_email_address(raw_header: Optional[str]) -> str:
    """
    Safely extract and normalize email address from an RFC 2822 header.
    E.g. 'John Doe <john@example.com>' -> 'john@example.com'
    """
    if not raw_header:
        return ""
    # email.utils.parseaddr handles quotes, angles, and edge cases safely
    _, addr = email.utils.parseaddr(raw_header)
    return addr.strip().lower() if addr else raw_header.strip().lower()


def parse_rfc2822_date(date_str: Optional[str]) -> datetime:
    """Parse an RFC 2822 date header into a UTC datetime, falling back to current UTC."""
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


class GmailReplyService:
    """
    Dedicated adapter for inspecting Gmail thread metadata to detect replies.
    """

    def __init__(
        self,
        credential_service: Optional[GmailCredentialService] = None,
        encryption_service: Optional[TokenEncryptionService] = None,
    ):
        self._credential_service = credential_service or GmailCredentialService(
            encryption_service=encryption_service
        )

    async def get_thread_messages_metadata(
        self,
        account: GmailAccount,
        thread_id: str,
    ) -> List[InboundMessageMetadata]:
        """
        Fetch thread metadata from Gmail API and extract structured message headers.
        Uses format=metadata to avoid fetching full message bodies.
        """
        if not thread_id or not thread_id.strip():
            raise GmailReplyMalformedError("Cannot inspect thread with empty thread_id.")

        # 1. Obtain ephemeral access token (fails closed if credential invalid)
        try:
            access_token = await self._credential_service.get_access_token(account)
        except CredentialRefreshError as exc:
            log.warning("Credential refresh failed for reply check", error=str(exc))
            raise GmailReplyAuthError(f"Gmail credential refresh failed: {str(exc)}") from exc

        # 2. Build bounded request querying only relevant metadata headers
        url = f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}"
        params = [
            ("format", "metadata"),
            ("metadataHeaders", "From"),
            ("metadataHeaders", "To"),
            ("metadataHeaders", "Subject"),
            ("metadataHeaders", "Date"),
            ("metadataHeaders", "Message-ID"),
            ("metadataHeaders", "In-Reply-To"),
            ("metadataHeaders", "References"),
        ]
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        # 3. Execute request with strict timeout
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            log.warning("Gmail API thread metadata request timed out", thread_id=thread_id)
            raise GmailReplyTimeoutError("Gmail API thread request timed out.") from exc
        except (httpx.NetworkError, httpx.ConnectError) as exc:
            log.warning("Network connection failure communicating with Gmail API", error=str(exc))
            raise GmailReplyNetworkError(f"Network error communicating with Gmail: {str(exc)}") from exc
        except Exception as exc:
            log.warning("Unexpected error communicating with Gmail API", error=str(exc))
            raise GmailReplyNetworkError(f"Failed to communicate with Gmail: {str(exc)}") from exc

        # 4. Classify HTTP status code
        if response.status_code == 401:
            log.warning("Gmail API returned 401 Unauthorized during thread inspection")
            raise GmailReplyAuthError("Gmail authentication failed or token revoked.")

        if response.status_code == 403:
            log.warning("Gmail API returned 403 Forbidden. Scope or access issue.")
            raise GmailReplyPermissionError("Gmail API returned 403 Forbidden. Check scopes.")

        if response.status_code == 429:
            log.warning("Gmail API rate limit exceeded (429)")
            raise GmailReplyRateLimitError("Gmail API rate limit exceeded. Retry later.")

        if response.status_code >= 500:
            log.warning("Gmail API server error", status_code=response.status_code)
            raise GmailReplyServerError(f"Google Gmail server error ({response.status_code}).")

        if response.status_code != 200:
            log.warning("Unexpected Gmail API response status", status_code=response.status_code)
            raise GmailReplyError(f"Gmail API returned unexpected HTTP {response.status_code}.")

        # 5. Parse JSON response
        try:
            data = response.json()
        except Exception as exc:
            raise GmailReplyMalformedError("Malformed response from Gmail API: non-JSON response.") from exc

        messages = data.get("messages")
        if messages is None:
            # An empty thread or missing messages key
            return []

        if not isinstance(messages, list):
            raise GmailReplyMalformedError("Gmail API response 'messages' field is not a list.")

        # 6. Parse metadata for each message
        parsed_messages: List[InboundMessageMetadata] = []
        for msg in messages:
            msg_id = msg.get("id")
            msg_thread_id = msg.get("threadId") or thread_id
            raw_snippet = msg.get("snippet", "")
            # Treat snippet as untrusted, truncate to 500 chars max
            snippet = raw_snippet[:500] if raw_snippet else None

            payload = msg.get("payload", {})
            headers_list = payload.get("headers", []) if isinstance(payload, dict) else []

            headers_map: Dict[str, str] = {}
            for h in headers_list:
                if isinstance(h, dict) and "name" in h and "value" in h:
                    headers_map[h["name"].lower()] = h["value"]

            sender_raw = headers_map.get("from", "")
            sender_email = extract_email_address(sender_raw)
            recipient_raw = headers_map.get("to", "")
            recipient_email = extract_email_address(recipient_raw)
            subject = headers_map.get("subject")
            date_raw = headers_map.get("date")
            received_at = parse_rfc2822_date(date_raw)
            in_reply_to = headers_map.get("in-reply-to")
            references = headers_map.get("references")

            parsed_messages.append(
                InboundMessageMetadata(
                    message_id=str(msg_id) if msg_id else "",
                    thread_id=str(msg_thread_id),
                    sender_email=sender_email,
                    recipient_email=recipient_email,
                    subject=subject[:500] if subject else None,
                    snippet=snippet,
                    received_at=received_at,
                    in_reply_to=in_reply_to,
                    references=references,
                )
            )

        return parsed_messages
