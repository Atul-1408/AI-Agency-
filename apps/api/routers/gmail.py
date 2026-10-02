"""
Gmail OAuth & Health Management Router.

Endpoints:
- GET  /api/v1/gmail/connect      -> Generate Google OAuth authorization URL
- GET  /api/v1/gmail/callback     -> Validate OAuth state, exchange code, encrypt and persist credentials
- GET  /api/v1/gmail/status       -> Query current Gmail connection and health status
- POST /api/v1/gmail/disconnect   -> Disconnect Gmail, invalidate token, and revoke credentials
- POST /api/v1/gmail/health-check -> Evaluate Gmail connectivity status with rate limit protection

SECURITY MANDATES:
- Only authenticated agency owners may access or manage Gmail connections.
- OAuth state tokens are signed, expiring (10m TTL), bound to owner, and replay protected via ConsumedOAuthState.
- Refresh tokens are NEVER logged, returned in responses, or stored in plaintext.
- No email sending, message dispatch, or inbox reading permissions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from core.config import settings
from core.database import get_db
from models import AgentRun, AgentRunStatus
from models.outreach import ConsumedOAuthState, GmailAccount, GmailConnectionStatus
from routers.auth import decode_token, require_owner
from schemas.gmail import (
    GmailConnectResponse,
    GmailDisconnectResponse,
    GmailHealthCheckResponse,
    GmailStatusResponse,
)
from services.gmail_credential_service import GmailCredentialService, HealthAssessmentResult
from services.gmail_oauth_service import (
    GmailOAuthConfigError,
    GmailOAuthError,
    GmailOAuthService,
    OAuthExchangeError,
    OAuthStateInvalidError,
    SAFE_SCOPE_LABELS,
)
from services.token_encryption import TokenEncryptionError, TokenEncryptionService

router = APIRouter()
log = structlog.get_logger(__name__)
_bearer = HTTPBearer(auto_error=False)


def verify_owner_access(owner_email: str) -> None:
    """
    IDOR Protection: Verify authenticated user matches configured agency owner.
    Prevents foreign or unauthorized owners from manipulating Gmail integrations.
    """
    if settings.OWNER_EMAIL and owner_email.lower().strip() != settings.OWNER_EMAIL.lower().strip():
        log.warning("IDOR/unauthorized owner access attempted on Gmail integration", owner=owner_email)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Authenticated user is not authorized to manage Gmail integrations for this agency",
        )


async def get_optional_owner(
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(_bearer)] = None,
) -> Optional[str]:
    """Extract owner from Bearer token if present, otherwise None."""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
        return payload.get("sub")
    except Exception:
        return None


async def log_gmail_audit(
    db: AsyncSession,
    action: str,
    owner_email: str,
    status: AgentRunStatus,
    input_data: Optional[Dict[str, Any]] = None,
    output_data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> AgentRun:
    """
    Record an immutable audit entry in agent_runs for every OAuth event.
    Sanitizes all payload data to strictly prevent secret leakage.
    """
    now = datetime.now(timezone.utc)
    forbidden_keys = {
        "token", "refresh_token", "access_token", "client_secret",
        "code", "authorization_code", "encrypted_refresh_token", "key"
    }

    def _sanitize(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not data:
            return {}
        return {k: v for k, v in data.items() if k.lower() not in forbidden_keys}

    run = AgentRun(
        agent_name="gmail_oauth",
        status=status,
        input_data={
            "action": action,
            "owner": owner_email,
            **_sanitize(input_data),
        },
        output_data=_sanitize(output_data),
        error_message=error_message,
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    await db.flush()
    return run


# ── 1. CONNECT ────────────────────────────────────────────────────────────────

@router.get("/connect", response_model=GmailConnectResponse)
async def connect_gmail(
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> GmailConnectResponse:
    """
    Initiate the secure Gmail OAuth connection flow.
    Returns a Google authorization URL with a signed, expiring state bound to the owner.
    """
    verify_owner_access(owner_email)
    oauth_service = GmailOAuthService()

    try:
        connect_data = oauth_service.get_authorization_url(owner_email)
    except GmailOAuthConfigError as exc:
        log.error("Gmail OAuth configuration error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Gmail integration unconfigured: {str(exc)}",
        ) from exc

    # Record OAuth initiated audit entry
    await log_gmail_audit(
        db=db,
        action="oauth_initiated",
        owner_email=owner_email,
        status=AgentRunStatus.COMPLETED,
        input_data={"action": "connect"},
    )
    await db.commit()

    return GmailConnectResponse(
        authorization_url=connect_data["authorization_url"],
        state=connect_data["state"],
    )


# ── 2. CALLBACK ───────────────────────────────────────────────────────────────

@router.get("/callback", response_model=GmailStatusResponse)
async def gmail_callback(
    code: Optional[str] = Query(None, description="Google OAuth authorization code"),
    state: Optional[str] = Query(None, description="Cryptographic owner-bound state token"),
    error: Optional[str] = Query(None, description="OAuth error code returned by Google"),
    caller_owner: Optional[str] = Depends(get_optional_owner),
    db: AsyncSession = Depends(get_db),
) -> GmailStatusResponse:
    """
    Process Google OAuth 2.0 callback:
    1. Validate state integrity, expiration, purpose, and owner binding.
    2. Prevent CSRF and state replay attacks via ConsumedOAuthState store.
    3. Exchange authorization code for tokens.
    4. Retrieve verified Google email identity.
    5. Verify Google account is not conflicting with another agency account.
    6. Encrypt refresh token using AES-256-GCM.
    7. Persist GmailAccount record as CONNECTED.
    """
    oauth_service = GmailOAuthService()
    encryption_service = TokenEncryptionService()

    # Handle user cancellation / Google error response
    if error:
        log.warning("Google returned OAuth error during callback", error=error)
        await log_gmail_audit(
            db=db,
            action="oauth_callback_failure",
            owner_email=caller_owner or "unknown",
            status=AgentRunStatus.FAILED,
            error_message=f"Google OAuth rejected: {error}",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google OAuth authorization failed: {error}",
        )

    # Validate state parameter presence
    if not state:
        await log_gmail_audit(
            db=db,
            action="oauth_callback_failure",
            owner_email=caller_owner or "unknown",
            status=AgentRunStatus.FAILED,
            error_message="Missing OAuth state parameter",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required OAuth state parameter",
        )

    try:
        claims = oauth_service.validate_and_decode_state(state, expected_owner_email=caller_owner)
    except OAuthStateInvalidError as exc:
        log.warning("OAuth state validation failed", error=str(exc))
        await log_gmail_audit(
            db=db,
            action="oauth_callback_failure",
            owner_email=caller_owner or "unknown",
            status=AgentRunStatus.FAILED,
            error_message=str(exc),
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    state_owner = claims["sub"]
    jti = claims.get("jti")

    # Enforce IDOR protection on bound state owner
    verify_owner_access(state_owner)

    # ── State Replay Protection ───────────────────────────────────────────────
    if not jti:
        log.warning("OAuth state missing jti identifier", owner=state_owner)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state missing replay protection token",
        )

    already_consumed = await db.scalar(
        select(ConsumedOAuthState).where(ConsumedOAuthState.jti == jti)
    )
    if already_consumed:
        log.warning("OAuth state replay detected", jti=jti, owner=state_owner)
        await log_gmail_audit(
            db=db,
            action="oauth_callback_failure",
            owner_email=state_owner,
            status=AgentRunStatus.FAILED,
            error_message="OAuth state already consumed (replay attack detected)",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state has already been consumed (replay attack detected).",
        )

    # Mark state as consumed in DB
    exp_ts = claims.get("exp")
    exp_dt = datetime.fromtimestamp(exp_ts, tz=timezone.utc) if exp_ts else (datetime.now(timezone.utc) + timedelta(minutes=10))
    db.add(ConsumedOAuthState(jti=jti, owner_id=state_owner, expires_at=exp_dt))
    await db.flush()

    if not code:
        await log_gmail_audit(
            db=db,
            action="oauth_callback_failure",
            owner_email=state_owner,
            status=AgentRunStatus.FAILED,
            error_message="Missing authorization code",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code from Google OAuth callback",
        )

    # Exchange authorization code for tokens
    try:
        tokens = await oauth_service.exchange_code_for_tokens(code)
    except (OAuthExchangeError, GmailOAuthConfigError) as exc:
        log.warning("OAuth code exchange failed", error=str(exc))
        await log_gmail_audit(
            db=db,
            action="oauth_callback_failure",
            owner_email=state_owner,
            status=AgentRunStatus.FAILED,
            error_message=str(exc),
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to exchange authorization code: {str(exc)}",
        ) from exc

    refresh_token = tokens.get("refresh_token")
    access_token = tokens.get("access_token")

    if not access_token:
        log.warning("Google token response did not contain access_token")
        await log_gmail_audit(
            db=db,
            action="oauth_callback_failure",
            owner_email=state_owner,
            status=AgentRunStatus.FAILED,
            error_message="Google response missing access_token",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid token response from Google: access_token missing",
        )

    # Retrieve verified Google email identity
    try:
        google_email = await oauth_service.get_user_identity(access_token)
    except OAuthExchangeError as exc:
        log.warning("Failed to retrieve Google user identity", error=str(exc))
        await log_gmail_audit(
            db=db,
            action="oauth_callback_failure",
            owner_email=state_owner,
            status=AgentRunStatus.FAILED,
            error_message=str(exc),
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to verify Google account identity: {str(exc)}",
        ) from exc

    # Check for Google account collision with another owner
    conflicting_account = await db.scalar(
        select(GmailAccount).where(
            GmailAccount.google_email == google_email,
            GmailAccount.owner_id != state_owner,
        )
    )
    if conflicting_account:
        log.warning("Google account already connected to another owner", google_email=google_email)
        await log_gmail_audit(
            db=db,
            action="oauth_callback_failure",
            owner_email=state_owner,
            status=AgentRunStatus.FAILED,
            error_message=f"Google account {google_email} is already linked to another owner",
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Google account is already linked to another agency owner.",
        )

    # Fetch existing account or check for existing refresh token
    existing_account = await db.scalar(
        select(GmailAccount).where(GmailAccount.owner_id == state_owner)
    )

    if not refresh_token:
        if existing_account and existing_account.encrypted_refresh_token:
            encrypted_refresh_token = existing_account.encrypted_refresh_token
        else:
            log.warning("Google OAuth did not provide a refresh_token")
            await log_gmail_audit(
                db=db,
                action="oauth_callback_failure",
                owner_email=state_owner,
                status=AgentRunStatus.FAILED,
                error_message="No refresh token returned by Google",
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Google OAuth did not return a refresh token. Re-consent required.",
            )
    else:
        # Encrypt the refresh token using AES-256-GCM
        try:
            encrypted_refresh_token = encryption_service.encrypt(refresh_token)
        except TokenEncryptionError as exc:
            log.error("Token encryption failed (Failing Closed)", error=str(exc))
            await log_gmail_audit(
                db=db,
                action="oauth_callback_failure",
                owner_email=state_owner,
                status=AgentRunStatus.FAILED,
                error_message="Token encryption failed",
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Security fault: failed to encrypt token credentials. Failing closed.",
            ) from exc

    now = datetime.now(timezone.utc)
    if not existing_account:
        account = GmailAccount(
            owner_id=state_owner,
            google_email=google_email,
            encrypted_refresh_token=encrypted_refresh_token,
            connection_status=GmailConnectionStatus.CONNECTED,
            token_created_at=now,
            last_token_refresh_at=now,
            last_health_check=now,
            last_error_at=None,
            last_error_code=None,
        )
        db.add(account)
    else:
        account = existing_account
        account.google_email = google_email
        account.encrypted_refresh_token = encrypted_refresh_token
        account.connection_status = GmailConnectionStatus.CONNECTED
        account.last_token_refresh_at = now
        account.last_health_check = now
        account.last_error_at = None
        account.last_error_code = None

    # Record successful callback & connection audit entries
    await log_gmail_audit(
        db=db,
        action="oauth_callback_success",
        owner_email=state_owner,
        status=AgentRunStatus.COMPLETED,
        input_data={"google_email": google_email},
    )
    await log_gmail_audit(
        db=db,
        action="gmail_connected",
        owner_email=state_owner,
        status=AgentRunStatus.COMPLETED,
        input_data={"google_email": google_email},
    )
    await db.commit()

    return GmailStatusResponse(
        connected=True,
        email=account.google_email,
        connection_status="CONNECTED",
        last_health_check=account.last_health_check,
        last_error_at=account.last_error_at,
        last_error_code=account.last_error_code,
        scopes=SAFE_SCOPE_LABELS,
    )


# ── 3. STATUS ─────────────────────────────────────────────────────────────────

@router.get("/status", response_model=GmailStatusResponse)
async def get_gmail_status(
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> GmailStatusResponse:
    """
    Get the safe connection status and metadata for the authenticated owner's Gmail account.
    NEVER returns refresh tokens, access tokens, client secrets, or encryption keys.
    """
    verify_owner_access(owner_email)

    account = await db.scalar(
        select(GmailAccount).where(GmailAccount.owner_id == owner_email)
    )

    if not account or account.connection_status == GmailConnectionStatus.DISCONNECTED:
        return GmailStatusResponse(
            connected=False,
            email=account.google_email if account else None,
            connection_status="DISCONNECTED",
            last_health_check=account.last_health_check if account else None,
            last_error_at=account.last_error_at if account else None,
            last_error_code=account.last_error_code if account else None,
            scopes=[],
        )

    if account.connection_status == GmailConnectionStatus.CONNECTED:
        return GmailStatusResponse(
            connected=True,
            email=account.google_email,
            connection_status="CONNECTED",
            last_health_check=account.last_health_check,
            last_error_at=account.last_error_at,
            last_error_code=account.last_error_code,
            scopes=SAFE_SCOPE_LABELS,
        )

    # ERROR state
    return GmailStatusResponse(
        connected=False,
        email=account.google_email,
        connection_status="ERROR",
        last_health_check=account.last_health_check,
        last_error_at=account.last_error_at,
        last_error_code=account.last_error_code,
        scopes=[],
    )


# ── 4. DISCONNECT ─────────────────────────────────────────────────────────────

@router.post("/disconnect", response_model=GmailDisconnectResponse)
async def disconnect_gmail(
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> GmailDisconnectResponse:
    """
    Disconnect linked Gmail account:
    1. Revokes Google credentials if possible.
    2. Purges stored encrypted refresh token.
    3. Sets status to DISCONNECTED.
    4. Audits the action in agent_runs.
    """
    verify_owner_access(owner_email)

    account = await db.scalar(
        select(GmailAccount).where(GmailAccount.owner_id == owner_email)
    )

    if not account:
        return GmailDisconnectResponse(
            message="No Gmail account was connected.",
            status="DISCONNECTED",
        )

    oauth_service = GmailOAuthService()
    encryption_service = TokenEncryptionService()

    # Attempt to revoke token with Google (gracefully tolerate network/revocation failures)
    if account.encrypted_refresh_token:
        try:
            token = encryption_service.decrypt(account.encrypted_refresh_token)
            await oauth_service.revoke_token(token)
        except Exception as exc:
            log.warning("Revocation during disconnect failed (proceeding with local purge)", error=str(exc))

    # Invalidate credentials locally
    account.encrypted_refresh_token = ""
    account.connection_status = GmailConnectionStatus.DISCONNECTED
    account.last_health_check = datetime.now(timezone.utc)
    account.last_error_at = None
    account.last_error_code = None

    # Audit the disconnection
    await log_gmail_audit(
        db=db,
        action="gmail_disconnected",
        owner_email=owner_email,
        status=AgentRunStatus.COMPLETED,
        input_data={"google_email": account.google_email},
    )
    await db.commit()

    return GmailDisconnectResponse(
        message="Gmail account disconnected successfully and credentials invalidated.",
        status="DISCONNECTED",
    )


# ── 5. HEALTH CHECK ───────────────────────────────────────────────────────────

@router.post("/health-check", response_model=GmailHealthCheckResponse)
async def check_gmail_health(
    force: bool = Query(False, description="Bypass the 10-second health check rate limit"),
    owner_email: str = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> GmailHealthCheckResponse:
    """
    Evaluate the health of the authenticated owner's connected Gmail account.
    Validates token decryption and refreshes token status against Google.
    Enforces a 10-second rate limit to prevent hammering Google servers.
    Does NOT send emails or access user messages.
    """
    verify_owner_access(owner_email)

    account = await db.scalar(
        select(GmailAccount).where(GmailAccount.owner_id == owner_email)
    )
    now = datetime.now(timezone.utc)

    if not account or account.connection_status == GmailConnectionStatus.DISCONNECTED:
        return GmailHealthCheckResponse(
            status="DISCONNECTED",
            email=account.google_email if account else None,
            last_health_check=now,
            is_healthy=False,
            error_code="DISCONNECTED",
            message="Gmail account is not connected",
        )

    # Rate limiting: prevent hammering Google OAuth endpoints
    if not force and account.last_health_check:
        last_check = account.last_health_check
        if last_check.tzinfo is None:
            last_check = last_check.replace(tzinfo=timezone.utc)
        elapsed_seconds = (now - last_check).total_seconds()
        if elapsed_seconds < 10.0:
            log.warning("Health check rate limit hit", owner=owner_email, elapsed=elapsed_seconds)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Health check rate limit exceeded. Please wait 10 seconds between checks.",
            )

    credential_service = GmailCredentialService()
    assessment: HealthAssessmentResult = await credential_service.verify_credential_health(account)

    # Update account state
    account.connection_status = assessment.status
    account.last_health_check = now

    status_label = assessment.status.name  # "CONNECTED", "DISCONNECTED", "ERROR"

    if assessment.is_healthy:
        account.last_error_at = None
        account.last_error_code = None
        await log_gmail_audit(
            db=db,
            action="gmail_health_success",
            owner_email=owner_email,
            status=AgentRunStatus.COMPLETED,
            input_data={"google_email": account.google_email},
        )
    else:
        account.last_error_at = now
        account.last_error_code = assessment.error_code
        await log_gmail_audit(
            db=db,
            action="gmail_health_failure",
            owner_email=owner_email,
            status=AgentRunStatus.FAILED,
            error_message=assessment.error_detail or f"Gmail health check assessed account as {status_label}",
            input_data={
                "google_email": account.google_email,
                "error_code": assessment.error_code,
                "assessed_status": status_label,
            },
        )
    await db.commit()

    return GmailHealthCheckResponse(
        status=status_label,
        email=account.google_email,
        last_health_check=now,
        is_healthy=assessment.is_healthy,
        error_code=assessment.error_code,
        message=assessment.error_detail or f"Gmail account health evaluated: {status_label}",
    )
