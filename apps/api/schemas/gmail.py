"""
Gmail OAuth & Health Response Schemas.

SECURITY MANDATE:
NEVER define fields for:
- refresh_token
- access_token
- client_secret
- authorization_code
- encryption_key
These must NEVER be serialized or returned in any API responses.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class GmailConnectResponse(BaseModel):
    """Safe response containing the Google OAuth authorization URL and state token."""
    authorization_url: str = Field(..., description="Google OAuth 2.0 authorization URL")
    state: str = Field(..., description="Cryptographically signed owner-bound state token")


class GmailStatusResponse(BaseModel):
    """
    Public connection status schema for the agency owner's linked Gmail account.
    Exposes only safe operational metadata.
    """
    model_config = ConfigDict(from_attributes=True)

    connected: bool = Field(..., description="Whether a Gmail account is actively connected and usable")
    email: Optional[str] = Field(None, description="Linked Google account email address")
    connection_status: str = Field(..., description="Connection status: CONNECTED, DISCONNECTED, or ERROR")
    last_health_check: Optional[datetime] = Field(None, description="Timestamp of the most recent health check")
    last_error_at: Optional[datetime] = Field(None, description="Timestamp of the most recent health check error")
    last_error_code: Optional[str] = Field(None, description="Machine-readable error classification code if unhealthy")
    scopes: List[str] = Field(default_factory=list, description="Authorized minimum OAuth scopes")


class GmailDisconnectResponse(BaseModel):
    """Response returned upon disconnecting a Gmail account."""
    message: str = Field(..., description="Status message")
    status: str = Field(..., description="Updated status: DISCONNECTED")


class GmailHealthCheckResponse(BaseModel):
    """Response returned upon triggering a Gmail account health check."""
    status: str = Field(..., description="Health status: CONNECTED, DISCONNECTED, or ERROR")
    email: Optional[str] = Field(None, description="Google account email")
    last_health_check: datetime = Field(..., description="Timestamp of completed check")
    is_healthy: bool = Field(..., description="Whether the connection is healthy")
    error_code: Optional[str] = Field(None, description="Classification of failure if unhealthy")
    message: str = Field(..., description="Summary of health assessment")
