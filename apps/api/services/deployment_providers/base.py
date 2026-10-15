"""
Phase 8 — Production Deployment Provider Abstraction.

Defines base classes, interface contracts, result data structures, and
custom exceptions for GitHub and Vercel hosting providers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from schemas.code_generation import GeneratedWebsiteFile


# ── Custom Exceptions ─────────────────────────────────────────────────────────

class DeploymentProviderError(Exception):
    """Base exception for all deployment provider errors."""
    def __init__(self, message: str, code: str = "PROVIDER_ERROR"):
        super().__init__(message)
        self.message = message
        self.code = code


class ProviderConfigurationError(DeploymentProviderError):
    """Raised when required credentials or settings are missing."""
    def __init__(self, message: str):
        super().__init__(message, code="MISSING_CONFIGURATION")


class ProviderAuthenticationError(DeploymentProviderError):
    """Raised when token is invalid or lacks necessary scopes."""
    def __init__(self, message: str):
        super().__init__(message, code="AUTHENTICATION_FAILED")


class ProviderSecurityError(DeploymentProviderError):
    """Raised when prohibited files, credentials, or dangerous paths are detected."""
    def __init__(self, message: str):
        super().__init__(message, code="SECURITY_VIOLATION")


class ProviderExecutionError(DeploymentProviderError):
    """Raised when provider API returns an unrecoverable failure during build or deploy."""
    def __init__(self, message: str, code: str = "EXECUTION_FAILED"):
        super().__init__(message, code=code)


# ── Result Schemas ────────────────────────────────────────────────────────────

class GitHubPublishResult(BaseModel):
    """Result of publishing website source files to a GitHub repository."""
    repo_url: str
    repo_name: str
    branch: str = "main"
    commit_sha: str
    commit_message: str
    published_files_count: int
    is_mock: bool = False


class VercelDeploymentResult(BaseModel):
    """Initial response from initiating a Vercel deployment."""
    deployment_id: str
    url: str
    production_url: Optional[str] = None
    inspector_url: Optional[str] = None
    status: str = "BUILDING"  # BUILDING, READY, ERROR, CANCELED
    is_mock: bool = False


class DeploymentStatusResult(BaseModel):
    """Telemetry and status polled from the hosting provider."""
    deployment_id: str
    status: str  # QUEUED, BUILDING, READY, ERROR, CANCELED
    url: Optional[str] = None
    production_url: Optional[str] = None
    build_logs: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    completed: bool = False
    is_mock: bool = False


class DomainConfigResult(BaseModel):
    """Result of binding or querying a custom domain."""
    domain: str
    configured: bool
    dns_records: List[Dict[str, Any]] = Field(default_factory=list)
    verification_status: str = "unconfigured"  # unconfigured, pending, verified
    ssl_status: str = "unconfigured"           # unconfigured, pending, active, error
    error: Optional[str] = None


class DomainVerificationResult(BaseModel):
    """Result of active DNS/SSL verification check."""
    domain: str
    verified: bool
    ssl_status: str  # unconfigured, pending, active, error
    dns_records: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


# ── Base Provider Interface ───────────────────────────────────────────────────

class DeploymentProviderBase(ABC):
    """Abstract interface contract for deployment integrations."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'vercel', 'github', 'mock')."""
        ...

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """True if the provider has all required credentials configured."""
        ...

    @abstractmethod
    async def publish_repository(
        self,
        repo_name: str,
        files: List[GeneratedWebsiteFile],
        branch: str = "main",
        commit_message: str = "Deploy website from AI Web Agency",
    ) -> GitHubPublishResult:
        """Publishes validated source files to a remote repository."""
        ...

    @abstractmethod
    async def create_deployment(
        self,
        project_name: str,
        files: List[GeneratedWebsiteFile],
        environment: str = "production",
        custom_domain: Optional[str] = None,
    ) -> VercelDeploymentResult:
        """Creates a deployment for the given files and environment."""
        ...

    @abstractmethod
    async def poll_deployment_status(
        self,
        deployment_id: str,
    ) -> DeploymentStatusResult:
        """Polls build progress and status of a deployment."""
        ...

    @abstractmethod
    async def configure_custom_domain(
        self,
        project_name: str,
        domain: str,
    ) -> DomainConfigResult:
        """Binds a custom domain and provides required DNS records."""
        ...

    @abstractmethod
    async def verify_custom_domain(
        self,
        project_name: str,
        domain: str,
    ) -> DomainVerificationResult:
        """Checks DNS propagation and SSL certificate issuance."""
        ...
