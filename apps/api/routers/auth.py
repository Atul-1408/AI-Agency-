"""
Authentication router.

Architecture decision (documented in PHASE1_STATUS.md):
  Single auth system — FastAPI JWT only.
  The Next.js dashboard calls this endpoint directly.
  No NextAuth, no OAuth2 in Phase 1.

Owner credentials are stored ONLY as environment variables:
  OWNER_EMAIL         — the owner's email address
  OWNER_PASSWORD_HASH — bcrypt hash of the password (generate with QUICKSTART.md)

Credentials are never stored in the database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import bcrypt as _bcrypt
import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from core.config import settings
from schemas import LoginRequest, TokenResponse

router = APIRouter()
log = structlog.get_logger(__name__)

_bearer = HTTPBearer(auto_error=False)


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt. Use this to generate OWNER_PASSWORD_HASH."""
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def _check_password(password: str, hashed: str) -> bool:
    """Constant-time bcrypt verification."""
    try:
        return _bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


# ── Token helpers ─────────────────────────────────────────────────────────────

def _create_access_token(subject: str) -> tuple[str, int]:
    """
    Create a signed JWT for the owner.
    Returns (token_string, expires_in_seconds).
    """
    expire_minutes = settings.JWT_EXPIRE_MINUTES
    expire = datetime.now(timezone.utc) + timedelta(minutes=expire_minutes)
    payload = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "role": "owner",
    }
    token = jwt.encode(payload, settings.APP_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, expire_minutes * 60


def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT. Raises HTTPException on invalid/expired tokens.
    """
    try:
        payload = jwt.decode(
            token, settings.APP_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("role") != "owner":
            raise JWTError("Invalid role")
        return payload
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ── Dependency ────────────────────────────────────────────────────────────────

async def require_owner(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """
    FastAPI dependency.
    Validates the Bearer JWT and returns the owner email.
    Use on any endpoint that requires authentication.

    Example:
        @router.get("/protected")
        async def protected(owner: str = Depends(require_owner)):
            ...
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials)
    return payload["sub"]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest) -> TokenResponse:
    """
    Owner login.

    Validates email and bcrypt password against OWNER_EMAIL and
    OWNER_PASSWORD_HASH environment variables.

    Returns a JWT on success.
    """
    # Check configuration
    if not settings.OWNER_EMAIL or not settings.OWNER_PASSWORD_HASH:
        log.error("Owner credentials not configured in environment")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Owner credentials not configured. "
                "Set OWNER_EMAIL and OWNER_PASSWORD_HASH in your .env file. "
                "See QUICKSTART.md for instructions."
            ),
        )

    # Validate credentials (constant-time comparison)
    email_matches = request.email.lower().strip() == settings.OWNER_EMAIL.lower().strip()
    password_matches = _check_password(request.password, settings.OWNER_PASSWORD_HASH)

    if not email_matches or not password_matches:
        log.warning("Failed login attempt", email=request.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token, expires_in = _create_access_token(request.email)
    log.info("Owner logged in", email=request.email)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me")
async def get_me(owner: str = Depends(require_owner)) -> dict:
    """Return the authenticated owner's email. Used to validate a JWT from the dashboard."""
    return {"email": owner, "role": "owner"}
