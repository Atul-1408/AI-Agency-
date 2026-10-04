"""
Gmail Thread Service — Phase 5 Stage 5.1.

Fetches complete Gmail thread content (FULL format) for authorized leads.
Used exclusively for Phase 5 Client Conversation Intelligence.

RESPONSIBILITIES:
- Fetch all messages in a Gmail thread using the owner's stored credential
- Parse PLAIN TEXT parts from each message (HTML stripped, attachments ignored)
- Classify message direction: OUTBOUND (from owner) vs INBOUND (from prospect)
- Enforce per-message body length cap (MAX_MESSAGE_BODY_CHARS)
- Fail closed on any credential, scope, or infrastructure failure
- Treat ALL message body content as UNTRUSTED EXTERNAL DATA

SECURITY MANDATES:
- Access tokens are ephemeral — obtained from GmailCredentialService, never stored
- No token values appear in logs, responses, or exception messages
- body_text from Gmail is UNTRUSTED DATA; never execute, never use as system prompt
- HTML content is stripped; only PLAIN TEXT is extracted and stored
- Attachment payloads are ignored entirely
- Thread ID must be validated by the caller before invoking this service
"""
from __future__ import annotations

import base64
import email.utils
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import structlog

from models.outreach import GmailAccount
from services.gmail_credential_service import CredentialRefreshError, GmailCredentialService
from services.token_encryption import TokenEncryptionService

log = structlog.get_logger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Maximum characters stored per message body (plain-text only, after HTML strip)
MAX_MESSAGE_BODY_CHARS: int = 10_000

# Maximum messages fetched from a single thread (prevents excessive API data)
MAX_THREAD_MESSAGES: int = 50

# Gmail API base URL
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Timeout for Gmail API requests (seconds)
GMAIL_TIMEOUT: float = 15.0


# ── Exceptions ────────────────────────────────────────────────────────────────

class GmailThreadError(Exception):
    """Base exception for all Gmail thread fetch failures."""
    pass


class GmailThreadAuthError(GmailThreadError):
    """Authentication or token credential failure (401)."""
    pass


class GmailThreadPermissionError(GmailThreadError):
    """Insufficient scope or permission error (403)."""
    pass


class GmailThreadRateLimitError(GmailThreadError):
    """Google Gmail API rate limit hit (429)."""
    pass


class GmailThreadServerError(GmailThreadError):
    """Google Gmail server-side outage or 5xx error."""
    pass


class GmailThreadTimeoutError(GmailThreadError):
    """Network timeout communicating with Gmail API."""
    pass


class GmailThreadNetworkError(GmailThreadError):
    """Network connection failure communicating with Gmail API."""
    pass


class GmailThreadMalformedError(GmailThreadError):
    """Malformed or invalid response from Gmail API."""
    pass


class GmailThreadNotFoundError(GmailThreadError):
    """Requested thread does not exist or is not accessible (404)."""
    pass


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GmailMessageData:
    """
    Safe, normalized representation of a single Gmail message.

    SECURITY: body_text is UNTRUSTED EXTERNAL DATA.
    It must never be used as a system prompt or executed.
    """
    gmail_message_id: str
    thread_id: str
    sender_email: str
    recipient_email: str
    subject: Optional[str]
    body_text: str          # Plain text, stripped HTML, capped at MAX_MESSAGE_BODY_CHARS
    received_at: datetime
    direction: str          # "outbound" | "inbound"
    position: int           # 0-indexed position in thread


@dataclass
class GmailThreadData:
    """
    Safe, normalized snapshot of a complete Gmail thread.
    Messages are ordered by position (ascending received_at).
    """
    thread_id: str
    messages: List[GmailMessageData] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @property
    def last_message_at(self) -> Optional[datetime]:
        if not self.messages:
            return None
        return max(m.received_at for m in self.messages)


# ── Helper Functions ──────────────────────────────────────────────────────────

def _extract_email_address(raw: Optional[str]) -> str:
    """Safely extract a normalized email address from an RFC 2822 header value."""
    if not raw:
        return ""
    _, addr = email.utils.parseaddr(raw)
    return addr.strip().lower() if addr else raw.strip().lower()


def _parse_date(date_str: Optional[str]) -> datetime:
    """Parse RFC 2822 date string to UTC datetime, defaulting to UTC now on failure."""
    if not date_str:
        return datetime.now(timezone.utc)
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _strip_html(text: str) -> str:
    """Remove HTML tags from text. Returns plain text."""
    # Remove script/style blocks and their contents
    text = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    # Replace block-level tags with newlines for readability
    text = re.sub(r"<(br|p|div|li|tr|td|th|h[1-6])[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Remove all remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Decode common HTML entities
    text = (
        text.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&nbsp;", " ")
            .replace("&quot;", '"')
            .replace("&#39;", "'")
    )
    # Collapse excessive whitespace/newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_plain_body(payload: Dict[str, Any]) -> str:
    """
    Recursively extract PLAIN TEXT body from a Gmail message payload.

    Strategy:
    1. If payload mimeType is text/plain — decode and return.
    2. If payload mimeType is text/html — strip HTML and return.
    3. If payload is multipart — recurse into parts, prefer text/plain over text/html.
    4. Attachments (filename present, or non-text mimeType) — skip entirely.

    Returns empty string if no plain or HTML text part found.
    """
    mime_type = payload.get("mimeType", "")
    parts = payload.get("parts", [])

    # Leaf node: encoded body
    body_data = payload.get("body", {}).get("data", "")

    if mime_type == "text/plain":
        if body_data:
            try:
                decoded = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
                return decoded
            except Exception:
                return ""
        return ""

    if mime_type == "text/html":
        if body_data:
            try:
                decoded = base64.urlsafe_b64decode(body_data + "==").decode("utf-8", errors="replace")
                return _strip_html(decoded)
            except Exception:
                return ""
        return ""

    # Attachment check: if filename is set, skip this part
    filename = payload.get("filename", "")
    if filename:
        return ""

    # Multipart: prefer text/plain; fall back to text/html
    if parts:
        plain_texts: List[str] = []
        html_texts: List[str] = []
        for part in parts:
            part_mime = part.get("mimeType", "")
            part_filename = part.get("filename", "")
            if part_filename:
                continue  # skip attachments
            text = _extract_plain_body(part)
            if not text:
                continue
            if "plain" in part_mime:
                plain_texts.append(text)
            elif "html" in part_mime:
                html_texts.append(text)
            elif "multipart" in part_mime:
                # Could be plain or html deeper in — add to plain
                plain_texts.append(text)

        if plain_texts:
            return "\n".join(plain_texts)
        if html_texts:
            return "\n".join(html_texts)

    return ""


# ── Service ───────────────────────────────────────────────────────────────────

class GmailThreadService:
    """
    Fetches a complete Gmail thread for Phase 5 client conversation intelligence.

    Uses the owner's stored, encrypted refresh token via GmailCredentialService.
    Returns a sanitized GmailThreadData dataclass.

    CALLER RESPONSIBILITIES:
    - Validate that the thread_id belongs to a verified InboundMessage for the
      authenticated owner's lead before calling this service.
    - The caller must NOT accept arbitrary thread IDs from request bodies.
    """

    def __init__(
        self,
        credential_service: Optional[GmailCredentialService] = None,
        encryption_service: Optional[TokenEncryptionService] = None,
    ) -> None:
        self._credential_service = credential_service or GmailCredentialService(
            encryption_service=encryption_service
        )

    async def fetch_thread(
        self,
        account: GmailAccount,
        thread_id: str,
        owner_email: str,
    ) -> GmailThreadData:
        """
        Fetch all messages in a Gmail thread and return a normalized snapshot.

        Args:
            account: The owner's GmailAccount record (with encrypted refresh token).
            thread_id: The Gmail thread ID to fetch (must be pre-validated by caller).
            owner_email: The authenticated owner email (used for direction classification).

        Returns:
            GmailThreadData with normalized, sanitized messages.

        Raises:
            GmailThreadAuthError: Token/credential failure.
            GmailThreadPermissionError: Insufficient OAuth scope.
            GmailThreadRateLimitError: Rate limit hit.
            GmailThreadServerError: Google server error.
            GmailThreadTimeoutError: Network timeout.
            GmailThreadNetworkError: Connection failure.
            GmailThreadMalformedError: Malformed API response.
            GmailThreadNotFoundError: Thread not found (404).
        """
        if not thread_id or not thread_id.strip():
            raise GmailThreadMalformedError("thread_id must not be empty.")

        # 1. Obtain ephemeral access token — never stored, never logged
        try:
            access_token = await self._credential_service.get_access_token(account)
        except CredentialRefreshError as exc:
            log.warning(
                "Credential refresh failed during thread fetch",
                thread_id=thread_id,
                error=str(exc),
            )
            raise GmailThreadAuthError(f"Gmail credential refresh failed: {str(exc)}") from exc

        # 2. Build request — fetch FULL format to get message bodies
        url = f"{GMAIL_API_BASE}/threads/{thread_id}"
        params = {"format": "full"}
        # Authorization header value is ephemeral — never logged
        req_headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}",
        }

        # 3. Execute with strict timeout
        try:
            async with httpx.AsyncClient(timeout=GMAIL_TIMEOUT) as client:
                response = await client.get(url, params=params, headers=req_headers)
        except httpx.TimeoutException as exc:
            log.warning("Gmail API thread fetch timed out", thread_id=thread_id)
            raise GmailThreadTimeoutError("Gmail thread request timed out.") from exc
        except (httpx.NetworkError, httpx.ConnectError) as exc:
            log.warning("Network failure during Gmail thread fetch", error=str(exc))
            raise GmailThreadNetworkError(f"Network error: {str(exc)}") from exc
        except Exception as exc:
            log.warning("Unexpected error during Gmail thread fetch", error=str(exc))
            raise GmailThreadNetworkError(f"Failed to communicate with Gmail: {str(exc)}") from exc

        # 4. Classify HTTP status
        if response.status_code == 401:
            log.warning("Gmail API returned 401 during thread fetch", thread_id=thread_id)
            raise GmailThreadAuthError("Gmail authentication failed or token revoked.")

        if response.status_code == 403:
            log.warning("Gmail API returned 403 during thread fetch — scope issue", thread_id=thread_id)
            raise GmailThreadPermissionError("Gmail API returned 403 Forbidden. Check OAuth scopes.")

        if response.status_code == 404:
            log.warning("Gmail thread not found", thread_id=thread_id)
            raise GmailThreadNotFoundError(f"Gmail thread '{thread_id}' not found or not accessible.")

        if response.status_code == 429:
            log.warning("Gmail API rate limit exceeded during thread fetch")
            raise GmailThreadRateLimitError("Gmail API rate limit exceeded. Retry later.")

        if response.status_code >= 500:
            log.warning("Gmail API server error during thread fetch", status=response.status_code)
            raise GmailThreadServerError(f"Google Gmail server error ({response.status_code}).")

        if response.status_code != 200:
            log.warning("Unexpected Gmail API response", status=response.status_code, thread_id=thread_id)
            raise GmailThreadError(f"Gmail API returned HTTP {response.status_code}.")

        # 5. Parse JSON
        try:
            data = response.json()
        except Exception as exc:
            raise GmailThreadMalformedError("Non-JSON response from Gmail API.") from exc

        if not isinstance(data, dict):
            raise GmailThreadMalformedError("Unexpected response structure from Gmail API.")

        raw_messages = data.get("messages")
        if raw_messages is None:
            return GmailThreadData(thread_id=thread_id)

        if not isinstance(raw_messages, list):
            raise GmailThreadMalformedError("Gmail API 'messages' field is not a list.")

        # 6. Enforce message cap
        capped = raw_messages[:MAX_THREAD_MESSAGES]

        # 7. Normalize each message
        normalized: List[GmailMessageData] = []
        for position, msg in enumerate(capped):
            msg_data = self._parse_message(
                msg=msg,
                thread_id=thread_id,
                owner_email=owner_email,
                position=position,
            )
            if msg_data:
                normalized.append(msg_data)

        # 8. Sort by received_at ascending (defensive; usually already sorted)
        normalized.sort(key=lambda m: m.received_at)
        # Re-assign positions after sort
        normalized = [
            GmailMessageData(
                gmail_message_id=m.gmail_message_id,
                thread_id=m.thread_id,
                sender_email=m.sender_email,
                recipient_email=m.recipient_email,
                subject=m.subject,
                body_text=m.body_text,
                received_at=m.received_at,
                direction=m.direction,
                position=idx,
            )
            for idx, m in enumerate(normalized)
        ]

        log.info(
            "Gmail thread fetched",
            thread_id=thread_id,
            message_count=len(normalized),
            capped=(len(raw_messages) > MAX_THREAD_MESSAGES),
        )

        return GmailThreadData(
            thread_id=thread_id,
            messages=normalized,
            fetched_at=datetime.now(timezone.utc),
        )

    def _parse_message(
        self,
        msg: Any,
        thread_id: str,
        owner_email: str,
        position: int,
    ) -> Optional[GmailMessageData]:
        """
        Parse a single Gmail message dict into a GmailMessageData.
        Returns None if parsing fails (skip rather than crash).
        """
        if not isinstance(msg, dict):
            return None

        msg_id = msg.get("id", "")
        if not msg_id:
            return None

        payload = msg.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        # Extract headers map
        headers_list = payload.get("headers", [])
        headers: Dict[str, str] = {}
        if isinstance(headers_list, list):
            for h in headers_list:
                if isinstance(h, dict) and "name" in h and "value" in h:
                    headers[h["name"].lower()] = h["value"]

        sender_email = _extract_email_address(headers.get("from", ""))
        recipient_email = _extract_email_address(headers.get("to", ""))
        subject_raw = headers.get("subject")
        subject = subject_raw[:500] if subject_raw else None
        received_at = _parse_date(headers.get("date"))

        # Direction classification based on sender
        direction = (
            "outbound"
            if sender_email and owner_email and sender_email == owner_email.lower().strip()
            else "inbound"
        )

        # Extract plain text body — UNTRUSTED EXTERNAL DATA
        raw_body = _extract_plain_body(payload)
        # Cap to MAX_MESSAGE_BODY_CHARS
        body_text = raw_body[:MAX_MESSAGE_BODY_CHARS] if raw_body else ""

        return GmailMessageData(
            gmail_message_id=str(msg_id),
            thread_id=thread_id,
            sender_email=sender_email,
            recipient_email=recipient_email,
            subject=subject,
            body_text=body_text,
            received_at=received_at,
            direction=direction,
            position=position,
        )
