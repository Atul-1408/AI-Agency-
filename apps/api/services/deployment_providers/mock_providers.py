"""
Phase 8 — Mock Deployment Providers for Testing and Local Simulation.

Guarantees:
1. Clearly labeled as mocks with `is_mock=True`.
2. Deterministic, reproducible commit SHAs and deployment IDs.
3. Realistic mock DNS records and domain verification flows.
4. ZERO external network requests.
5. ZERO code execution on the host machine.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional
import uuid

from schemas.code_generation import GeneratedWebsiteFile
from services.deployment_providers.base import (
    DeploymentProviderBase,
    DeploymentStatusResult,
    DomainConfigResult,
    DomainVerificationResult,
    GitHubPublishResult,
    ProviderSecurityError,
    VercelDeploymentResult,
)
from services.deployment_providers.github_provider import (
    PROHIBITED_FILE_PATTERNS,
    SECRET_CONTENT_PATTERNS,
)


class MockDeploymentProvider(DeploymentProviderBase):
    """
    Deterministic simulated provider for automated testing and local verification.
    Clearly marks all operations with is_mock=True.
    """

    def __init__(self, simulate_failure: bool = False, failure_reason: str = "Simulated build error"):
        self.simulate_failure = simulate_failure
        self.failure_reason = failure_reason

    @property
    def name(self) -> str:
        return "mock"

    @property
    def is_configured(self) -> bool:
        return True

    def _validate_files(self, files: List[GeneratedWebsiteFile]) -> None:
        """Enforces security screening even in mock mode."""
        for f in files:
            norm_path = f.path.replace("\\", "/").strip().lstrip("/")
            if ".." in norm_path or norm_path.startswith("/"):
                raise ProviderSecurityError(f"Malicious path traversal detected: '{f.path}'")

            for pattern in PROHIBITED_FILE_PATTERNS:
                if re.search(pattern, norm_path, re.IGNORECASE):
                    raise ProviderSecurityError(
                        f"Prohibited file '{f.path}' cannot be published in deployment."
                    )

            for secret_pattern in SECRET_CONTENT_PATTERNS:
                if secret_pattern.search(f.content):
                    raise ProviderSecurityError(
                        f"Secret pattern detected in file '{f.path}'. Publishing aborted."
                    )

    async def publish_repository(
        self,
        repo_name: str,
        files: List[GeneratedWebsiteFile],
        branch: str = "main",
        commit_message: str = "Deploy website from AI Web Agency",
    ) -> GitHubPublishResult:
        """Simulates GitHub repo synchronization with deterministic commit SHA."""
        self._validate_files(files)

        slug = repo_name.lower().replace(" ", "-")
        # Deterministic SHA based on filenames and message
        h = hashlib.sha1()
        h.update(slug.encode("utf-8"))
        h.update(branch.encode("utf-8"))
        for f in sorted(files, key=lambda x: x.path):
            h.update(f.path.encode("utf-8"))
            h.update(f.checksum.encode("utf-8") if f.checksum else b"")
        commit_sha = h.hexdigest()

        return GitHubPublishResult(
            repo_url=f"https://github.com/mock-agency/{slug}",
            repo_name=f"mock-agency/{slug}",
            branch=branch,
            commit_sha=commit_sha,
            commit_message=commit_message,
            published_files_count=len(files),
            is_mock=True,
        )

    async def create_deployment(
        self,
        project_name: str,
        files: List[GeneratedWebsiteFile],
        environment: str = "production",
        custom_domain: Optional[str] = None,
    ) -> VercelDeploymentResult:
        """Simulates Vercel deployment creation."""
        self._validate_files(files)

        slug = project_name.lower().replace(" ", "-")[:40]
        dep_id = f"dpl_mock_{uuid.uuid4().hex[:12]}"
        env_label = "preview" if environment.lower() == "preview" else "prod"
        deploy_url = f"https://{slug}-{env_label}.mock.agen.dev"
        prod_url = f"https://{custom_domain}" if custom_domain else f"https://{slug}.mock.agen.site"

        if self.simulate_failure:
            return VercelDeploymentResult(
                deployment_id=dep_id,
                url=deploy_url,
                production_url=None,
                inspector_url=f"https://vercel.com/mock-agency/{slug}/{dep_id}",
                status="ERROR",
                is_mock=True,
            )

        return VercelDeploymentResult(
            deployment_id=dep_id,
            url=deploy_url,
            production_url=prod_url if environment.lower() == "production" else None,
            inspector_url=f"https://vercel.com/mock-agency/{slug}/{dep_id}",
            status="READY",
            is_mock=True,
        )

    async def poll_deployment_status(self, deployment_id: str) -> DeploymentStatusResult:
        """Simulates deployment status polling."""
        if self.simulate_failure:
            return DeploymentStatusResult(
                deployment_id=deployment_id,
                status="ERROR",
                error_code="BUILD_ERROR",
                error_message=self.failure_reason,
                completed=True,
                is_mock=True,
            )

        return DeploymentStatusResult(
            deployment_id=deployment_id,
            status="READY",
            url=f"https://mock-app-{deployment_id[-6:]}.mock.agen.dev",
            production_url=f"https://mock-app-{deployment_id[-6:]}.mock.agen.site",
            build_logs="Mock build logs: Compiled 8 pages in 1.4s. 0 errors, 0 warnings.",
            completed=True,
            is_mock=True,
        )

    async def configure_custom_domain(
        self,
        project_name: str,
        domain: str,
    ) -> DomainConfigResult:
        """Simulates custom domain configuration with standard DNS requirements."""
        clean_domain = domain.strip().lower()
        dns_records = [
            {
                "type": "A",
                "name": "@",
                "value": "76.76.21.21",
                "description": "Apex A Record for Vercel edge network",
            },
            {
                "type": "CNAME",
                "name": "www",
                "value": "cname.vercel-dns.com",
                "description": "Subdomain CNAME record for Vercel CDN",
            },
        ]

        # In mock mode, if domain ends with '.unverified', keep unconfigured
        if clean_domain.endswith(".unverified"):
            return DomainConfigResult(
                domain=clean_domain,
                configured=False,
                dns_records=dns_records,
                verification_status="unconfigured",
                ssl_status="unconfigured",
                error="DNS records not configured at registrar.",
            )

        return DomainConfigResult(
            domain=clean_domain,
            configured=True,
            dns_records=dns_records,
            verification_status="pending",
            ssl_status="pending",
        )

    async def verify_custom_domain(
        self,
        project_name: str,
        domain: str,
    ) -> DomainVerificationResult:
        """Simulates checking DNS and SSL status."""
        clean_domain = domain.strip().lower()
        dns_records = [
            {"type": "A", "name": "@", "value": "76.76.21.21"},
            {"type": "CNAME", "name": "www", "value": "cname.vercel-dns.com"},
        ]

        if clean_domain.endswith(".unverified"):
            return DomainVerificationResult(
                domain=clean_domain,
                verified=False,
                ssl_status="unconfigured",
                dns_records=dns_records,
                error="Domain resolution failed: A record not pointing to 76.76.21.21.",
            )

        # Verified domain simulation
        return DomainVerificationResult(
            domain=clean_domain,
            verified=True,
            ssl_status="active",
            dns_records=dns_records,
        )
