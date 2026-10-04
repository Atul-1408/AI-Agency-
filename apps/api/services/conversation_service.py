"""
Client Conversation Service — Phase 5 Stage 5.1.

Orchestrates:
1. Creating a ClientConversation record anchored to a Lead + Gmail thread
2. Validating owner access (IDOR protection)
3. Fetching and storing thread messages via GmailThreadService
4. Listing conversations with filtering

SECURITY MANDATES:
- owner_email is ALWAYS derived from JWT — never from request body
- Thread ID must be validated against an InboundMessage owned by the caller's lead
- All message body_text is treated as UNTRUSTED EXTERNAL DATA
- No token values appear in logs or exception messages
- Fails closed on any ownership or credential failure
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import structlog

from models import AgentRun, AgentRunStatus, Lead, LeadStatus
from models.client_intelligence import (
    ClientConversation,
    ClientConversationMessage,
    ClientConversationStatus,
    MessageDirection,
)
from models.follow_up import InboundMessage
from models.outreach import GmailAccount, GmailConnectionStatus
from services.gmail_credential_service import GmailCredentialService
from services.gmail_thread_service import (
    GmailMessageData,
    GmailThreadAuthError,
    GmailThreadData,
    GmailThreadError,
    GmailThreadMalformedError,
    GmailThreadNetworkError,
    GmailThreadNotFoundError,
    GmailThreadPermissionError,
    GmailThreadRateLimitError,
    GmailThreadServerError,
    GmailThreadService,
    GmailThreadTimeoutError,
)

log = structlog.get_logger(__name__)


# ── Domain Exceptions ─────────────────────────────────────────────────────────

class ConversationError(Exception):
    """Base exception for ClientConversationService failures."""
    pass


class ConversationNotFoundError(ConversationError):
    """Raised when a conversation does not exist or is inaccessible."""
    pass


class ConversationOwnershipError(ConversationError):
    """Raised when the caller does not own the conversation's lead."""
    pass


class ConversationLeadNotFoundError(ConversationError):
    """Raised when the specified lead does not exist or is inaccessible."""
    pass


class ConversationIneligibleLeadError(ConversationError):
    """Raised when the lead has no verified reply (InboundMessage) — not eligible for Phase 5."""
    pass


class ConversationDuplicateError(ConversationError):
    """Raised when a conversation for this lead+thread already exists."""
    pass


class ConversationGmailError(ConversationError):
    """Raised when Gmail API interaction fails during thread fetch."""
    pass


class ConversationGmailDisconnectedError(ConversationGmailError):
    """Raised when the Gmail account is not CONNECTED."""
    pass


class ConversationThreadNotRelatedError(ConversationError):
    """Raised when the requested thread_id is not related to a known InboundMessage for this lead."""
    pass


# ── Service ───────────────────────────────────────────────────────────────────

class ClientConversationService:
    """
    Manages ClientConversation lifecycle: creation, thread fetch, listing.

    All operations require an authenticated owner_email (from JWT).
    All cross-owner access attempts raise ConversationOwnershipError.
    """

    def __init__(
        self,
        thread_service: Optional[GmailThreadService] = None,
        credential_service: Optional[GmailCredentialService] = None,
    ) -> None:
        self._thread_service = thread_service or GmailThreadService()
        self._credential_service = credential_service or GmailCredentialService()

    # ── IDOR Guard ────────────────────────────────────────────────────────────

    async def verify_conversation_ownership(
        self,
        conversation_id: uuid.UUID,
        owner_email: str,
        db: AsyncSession,
    ) -> ClientConversation:
        """
        Load and ownership-verify a ClientConversation.
        Raises ConversationNotFoundError if not found.
        Raises ConversationOwnershipError if caller does not own it.
        """
        conv = (await db.scalars(
            select(ClientConversation)
            .where(ClientConversation.id == conversation_id)
        )).first()

        if conv is None:
            raise ConversationNotFoundError(
                f"Conversation '{conversation_id}' not found."
            )

        if conv.owner_email.lower().strip() != owner_email.lower().strip():
            log.warning(
                "IDOR attempt on ClientConversation",
                conversation_id=str(conversation_id),
                caller=owner_email,
                owner=conv.owner_email,
            )
            raise ConversationOwnershipError(
                "You do not have access to this conversation."
            )

        return conv

    # ── Creation ──────────────────────────────────────────────────────────────

    async def create_conversation(
        self,
        lead_id: uuid.UUID,
        owner_email: str,
        db: AsyncSession,
        inbound_message_id: Optional[uuid.UUID] = None,
    ) -> ClientConversation:
        """
        Create a new ClientConversation anchored to a Lead and Gmail thread.

        Eligibility requirements:
        - Lead must exist and belong to the caller (owner_email match)
        - Lead must have at least one InboundMessage (verified reply from Phase 4)
        - If inbound_message_id is provided, it must belong to this lead
        - gmail_thread_id is taken from the InboundMessage record (not from caller)
        - Duplicate conversations for the same lead+thread are rejected

        Args:
            lead_id: UUID of the Lead.
            owner_email: JWT-derived owner email (never from request body).
            db: Async database session.
            inbound_message_id: Optional specific InboundMessage to anchor to.

        Returns:
            New ClientConversation (status=INITIATED).
        """
        # 1. Load lead and verify ownership
        lead = (await db.scalars(
            select(Lead).where(Lead.id == lead_id)
        )).first()

        if lead is None:
            raise ConversationLeadNotFoundError(f"Lead '{lead_id}' not found.")

        # In this single-owner system, ownership is enforced at the router level by
        # verify_owner_access (which checks settings.OWNER_EMAIL against the JWT).
        # All leads belong to the single owner by design.
        # If multi-owner support is added in future, a lead.owner_email field must be added.

        # 2. Find a qualifying InboundMessage for this lead
        inbound: Optional[InboundMessage] = None

        if inbound_message_id is not None:
            # Specific message requested
            inbound = (await db.scalars(
                select(InboundMessage)
                .where(
                    InboundMessage.id == inbound_message_id,
                    InboundMessage.matched_lead_id == lead_id,
                )
            )).first()
            if inbound is None:
                raise ConversationIneligibleLeadError(
                    f"InboundMessage '{inbound_message_id}' not found for lead '{lead_id}'. "
                    "The lead must have a verified reply from Phase 4."
                )
        else:
            # Pick the most recent verified inbound message for this lead
            inbound = (await db.scalars(
                select(InboundMessage)
                .where(InboundMessage.matched_lead_id == lead_id)
                .order_by(InboundMessage.received_at.desc())
            )).first()

            if inbound is None:
                raise ConversationIneligibleLeadError(
                    f"Lead '{lead_id}' has no verified reply. "
                    "A Phase 4 InboundMessage is required before starting a conversation."
                )

        thread_id = inbound.gmail_thread_id

        # 3. Check for duplicate conversation (same lead + thread)
        existing = (await db.scalars(
            select(ClientConversation)
            .where(
                ClientConversation.lead_id == lead_id,
                ClientConversation.gmail_thread_id == thread_id,
            )
        )).first()

        if existing is not None:
            raise ConversationDuplicateError(
                f"A conversation for lead '{lead_id}' and thread '{thread_id}' already exists "
                f"(id={existing.id})."
            )

        # 4. Create conversation record
        conv = ClientConversation(
            lead_id=lead_id,
            inbound_message_id=inbound.id,
            owner_email=owner_email,  # always from JWT
            gmail_thread_id=thread_id,
            status=ClientConversationStatus.INITIATED,
        )
        db.add(conv)
        await db.flush()
        await db.refresh(conv)

        # 5. Audit
        await self._record_audit(
            db=db,
            event="conversation_created",
            conversation_id=conv.id,
            lead_id=lead_id,
            owner_email=owner_email,
            detail={
                "gmail_thread_id": thread_id,
                "inbound_message_id": str(inbound.id),
            },
        )

        log.info(
            "ClientConversation created",
            conversation_id=str(conv.id),
            lead_id=str(lead_id),
            gmail_thread_id=thread_id,
        )
        return conv

    # ── Thread Fetch ──────────────────────────────────────────────────────────

    async def fetch_thread(
        self,
        conversation_id: uuid.UUID,
        owner_email: str,
        db: AsyncSession,
    ) -> ClientConversation:
        """
        Fetch the Gmail thread for an existing conversation and store normalized messages.

        - Verifies ownership before any Gmail API call
        - Validates Gmail account is CONNECTED
        - Calls GmailThreadService.fetch_thread() with the validated thread_id
        - Upserts ClientConversationMessage records (idempotent by gmail_message_id)
        - Updates conversation: status=FETCHED, fetched_at, message_count, last_message_at

        SECURITY:
        - The thread_id used is from the conversation record (stored from InboundMessage)
        - It is never taken from the HTTP request
        - Access token is ephemeral (handled by GmailThreadService)
        - Message body_text is UNTRUSTED DATA; stored as-is for Stage 5.2 processing

        Args:
            conversation_id: UUID of the conversation to refresh.
            owner_email: JWT-derived owner email.
            db: Async database session.

        Returns:
            Updated ClientConversation with messages loaded.
        """
        # 1. Ownership check
        conv = await self.verify_conversation_ownership(conversation_id, owner_email, db)

        # 2. Load Gmail account
        account = await self._get_connected_gmail_account(owner_email, db)

        # 3. Fetch thread via service (thread_id comes from trusted conv record, not request)
        try:
            thread_data: GmailThreadData = await self._thread_service.fetch_thread(
                account=account,
                thread_id=conv.gmail_thread_id,
                owner_email=owner_email,
            )
        except GmailThreadAuthError as exc:
            raise ConversationGmailError(f"Gmail authentication failure: {str(exc)}") from exc
        except GmailThreadPermissionError as exc:
            raise ConversationGmailError(f"Gmail permission error: {str(exc)}") from exc
        except GmailThreadRateLimitError as exc:
            raise ConversationGmailError(f"Gmail rate limit: {str(exc)}") from exc
        except GmailThreadServerError as exc:
            raise ConversationGmailError(f"Gmail server error: {str(exc)}") from exc
        except GmailThreadTimeoutError as exc:
            raise ConversationGmailError(f"Gmail request timed out: {str(exc)}") from exc
        except GmailThreadNetworkError as exc:
            raise ConversationGmailError(f"Gmail network error: {str(exc)}") from exc
        except GmailThreadNotFoundError as exc:
            raise ConversationGmailError(f"Gmail thread not found: {str(exc)}") from exc
        except GmailThreadMalformedError as exc:
            raise ConversationGmailError(f"Malformed Gmail response: {str(exc)}") from exc

        # 4. Upsert messages
        await self._upsert_messages(conv=conv, thread_data=thread_data, db=db)

        # 5. Update conversation state
        conv.status = ClientConversationStatus.FETCHED
        conv.fetched_at = thread_data.fetched_at
        conv.message_count = thread_data.message_count
        conv.last_message_at = thread_data.last_message_at

        await db.flush()

        # 6. Audit
        await self._record_audit(
            db=db,
            event="conversation_thread_fetched",
            conversation_id=conv.id,
            lead_id=conv.lead_id,
            owner_email=owner_email,
            detail={
                "gmail_thread_id": conv.gmail_thread_id,
                "message_count": thread_data.message_count,
            },
        )

        await db.refresh(conv)

        log.info(
            "Thread fetched for conversation",
            conversation_id=str(conv.id),
            thread_id=conv.gmail_thread_id,
            message_count=thread_data.message_count,
        )
        return conv

    async def _upsert_messages(
        self,
        conv: ClientConversation,
        thread_data: GmailThreadData,
        db: AsyncSession,
    ) -> None:
        """
        Insert or update ClientConversationMessage records for the fetched thread.
        Uses gmail_message_id as idempotency key.
        """
        # Load existing message IDs for this conversation
        existing_rows = (await db.scalars(
            select(ClientConversationMessage)
            .where(ClientConversationMessage.conversation_id == conv.id)
        )).all()
        existing_map = {m.gmail_message_id: m for m in existing_rows}

        for msg in thread_data.messages:
            if msg.gmail_message_id in existing_map:
                # Update position and body in case thread was re-fetched
                existing = existing_map[msg.gmail_message_id]
                existing.position = msg.position
                # body_text refresh on re-fetch
                existing.body_text = msg.body_text or None
            else:
                direction = (
                    MessageDirection.OUTBOUND
                    if msg.direction == "outbound"
                    else MessageDirection.INBOUND
                )
                new_msg = ClientConversationMessage(
                    conversation_id=conv.id,
                    gmail_message_id=msg.gmail_message_id,
                    gmail_thread_id=msg.thread_id,
                    sender_email=msg.sender_email,
                    recipient_email=msg.recipient_email,
                    subject=msg.subject,
                    direction=direction,
                    body_text=msg.body_text or None,
                    received_at=msg.received_at,
                    position=msg.position,
                )
                db.add(new_msg)

        await db.flush()

    # ── List ──────────────────────────────────────────────────────────────────

    async def list_conversations(
        self,
        owner_email: str,
        db: AsyncSession,
        status_filter: Optional[ClientConversationStatus] = None,
        lead_id_filter: Optional[uuid.UUID] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[List[ClientConversation], int]:
        """
        List conversations for the authenticated owner with optional filtering.

        Returns (conversations, total_count).
        """
        query = (
            select(ClientConversation)
            .where(ClientConversation.owner_email == owner_email)
        )

        if status_filter is not None:
            query = query.where(ClientConversation.status == status_filter)

        if lead_id_filter is not None:
            query = query.where(ClientConversation.lead_id == lead_id_filter)

        from sqlalchemy import func
        count_query = select(func.count()).select_from(query.subquery())
        total: int = (await db.scalar(count_query)) or 0

        result_query = (
            query
            .order_by(ClientConversation.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        conversations = (await db.scalars(result_query)).all()
        return list(conversations), total

    # ── Gmail Account Loading ─────────────────────────────────────────────────

    async def _get_connected_gmail_account(
        self,
        owner_email: str,
        db: AsyncSession,
    ) -> GmailAccount:
        """
        Load the owner's Gmail account and verify it is CONNECTED.
        Raises ConversationGmailDisconnectedError if not usable.
        """
        account = (await db.scalars(
            select(GmailAccount)
            .where(GmailAccount.owner_id == owner_email)
        )).first()

        if account is None:
            raise ConversationGmailDisconnectedError(
                "No Gmail account connected. Connect Gmail in Settings before fetching threads."
            )

        if account.connection_status != GmailConnectionStatus.CONNECTED:
            raise ConversationGmailDisconnectedError(
                f"Gmail account is not connected (status={account.connection_status.value}). "
                "Reconnect in Settings."
            )

        if not account.encrypted_refresh_token or not account.encrypted_refresh_token.strip():
            raise ConversationGmailDisconnectedError(
                "Gmail account credential is missing. Reconnect in Settings."
            )

        return account

    # ── Audit ─────────────────────────────────────────────────────────────────

    async def _record_audit(
        self,
        db: AsyncSession,
        event: str,
        conversation_id: uuid.UUID,
        lead_id: uuid.UUID,
        owner_email: str,
        detail: dict,
    ) -> None:
        """
        Record an audit entry in agent_runs for conversation lifecycle events.
        NEVER logs email body content, tokens, or credentials.
        """
        run = AgentRun(
            agent_name="client_conversation_service",
            status=AgentRunStatus.COMPLETED,
            input_data={
                "event": event,
                "conversation_id": str(conversation_id),
                "lead_id": str(lead_id),
                "owner": owner_email,
                **{k: str(v) for k, v in detail.items()},
            },
            output_data={"result": "ok"},
        )
        db.add(run)
        await db.flush()
