"""
Phase 8 — GitHub Provider Integration.

Implements secure Git repository creation and source code synchronization via the
GitHub REST API (v3 / 2022-11-28).

Security Guarantees:
1. Strict secret and credential scanning before any file is uploaded.
2. Rejection of prohibited files (.env, .pem, .key, id_rsa, credentials, node_modules).
3. Path canonicalization and directory traversal prevention.
4. Prevents accidental overwrites by disallowing force-pushing.
5. All access tokens and sensitive credentials are redacted from error logs and traces.
"""
from __future__ import annotations

import base64
import re
from typing import Any, Dict, List, Optional
import httpx
import structlog

from core.config import settings
from schemas.code_generation import GeneratedWebsiteFile
from services.deployment_providers.base import (
    GitHubPublishResult,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderExecutionError,
    ProviderSecurityError,
)

log = structlog.get_logger(__name__)

# Patterns for files prohibited from publishing
PROHIBITED_FILE_PATTERNS = [
    r"(^|/)\.env($|\..*)",
    r".*\.pem$",
    r".*\.key$",
    r".*id_rsa.*",
    r".*credentials.*\.json$",
    r".*\.secret$",
    r".*\.token$",
    r"(^|/)node_modules/.*",
    r"(^|/)\.git/.*",
    r"(^|/)\.next/.*",
    r"(^|/)dist/.*",
    r"(^|/)\.cache/.*",
]

# Sensitive content signatures (private keys, secrets)
SECRET_CONTENT_PATTERNS = [
    re.compile(r"-----BEGIN (RSA|OPENSSH|EC|DSA|PGP|ENCRYPTED) PRIVATE KEY-----"),
    re.compile(r"ghp_[A-Za-z0-9_]{36}"),
    re.compile(r"vercel_[A-Za-z0-9_]{24}"),
    re.compile(r"AI_API_KEY\s*=\s*['\"][A-Za-z0-9_-]{10,}['\"]"),
]


class GitHubProvider:
    """Production GitHub client with enterprise security safeguards."""

    def __init__(
        self,
        token: Optional[str] = None,
        owner: Optional[str] = None,
        api_base_url: str = "https://api.github.com",
    ):
        self._token = token or settings.GITHUB_TOKEN
        self._owner = owner or settings.GITHUB_ORG or settings.GITHUB_USERNAME
        self._api_base_url = api_base_url.rstrip("/")

    @property
    def is_configured(self) -> bool:
        """True if GitHub API token is populated."""
        return bool(self._token and self._token.strip())

    def _headers(self) -> Dict[str, str]:
        if not self.is_configured:
            raise ProviderConfigurationError("GitHub token is not configured.")
        return {
            "Authorization": f"Bearer {self._token.strip()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AI-Web-Agency-Agent/Phase8",
        }

    def _redact_message(self, message: str) -> str:
        """Removes tokens or sensitive substrings from output strings."""
        if not self._token:
            return message
        return message.replace(self._token, "[REDACTED_GITHUB_TOKEN]")

    def validate_files_security(self, files: List[GeneratedWebsiteFile]) -> None:
        """
        Validates all files against path traversal, prohibited filenames, and secret content.
        Raises ProviderSecurityError if any violation is detected.
        """
        for f in files:
            norm_path = f.path.replace("\\", "/").strip().lstrip("/")

            # 1. Traversal check
            if ".." in norm_path or norm_path.startswith("/"):
                raise ProviderSecurityError(f"Malicious path traversal detected: '{f.path}'")

            # 2. Prohibited filenames check
            for pattern in PROHIBITED_FILE_PATTERNS:
                if re.search(pattern, norm_path, re.IGNORECASE):
                    raise ProviderSecurityError(
                        f"Prohibited file '{f.path}' cannot be published to GitHub repository."
                    )

            # 3. Secret content scanning
            for secret_pattern in SECRET_CONTENT_PATTERNS:
                if secret_pattern.search(f.content):
                    raise ProviderSecurityError(
                        f"Secret or private key pattern detected in file '{f.path}'. Publishing aborted."
                    )

    async def ensure_repository(self, repo_name: str, private: bool = True) -> Dict[str, Any]:
        """
        Checks if the repository exists; if not, creates a new one.
        Handles both user accounts and organization accounts.
        """
        if not self.is_configured:
            raise ProviderConfigurationError("GitHub token is unconfigured.")

        headers = self._headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Check if repo exists
            target_owner = self._owner
            if target_owner:
                check_url = f"{self._api_base_url}/repos/{target_owner}/{repo_name}"
            else:
                # Use current authenticated user's repos
                user_res = await client.get(f"{self._api_base_url}/user", headers=headers)
                if user_res.status_code == 401:
                    raise ProviderAuthenticationError("Invalid or expired GitHub token.")
                user_res.raise_for_status()
                user_login = user_res.json()["login"]
                check_url = f"{self._api_base_url}/repos/{user_login}/{repo_name}"

            res = await client.get(check_url, headers=headers)
            if res.status_code == 200:
                return res.json()

            # Repository does not exist — create it
            create_payload = {
                "name": repo_name,
                "description": "Website generated and verified by AI Web Agency Agent",
                "private": private,
                "auto_init": True,  # Creates initial commit with README so branch exists
            }

            if settings.GITHUB_ORG:
                create_url = f"{self._api_base_url}/orgs/{settings.GITHUB_ORG}/repos"
            else:
                create_url = f"{self._api_base_url}/user/repos"

            create_res = await client.post(create_url, headers=headers, json=create_payload)
            if create_res.status_code in (200, 201):
                return create_res.json()

            clean_err = self._redact_message(create_res.text)
            raise ProviderExecutionError(
                f"Failed to create GitHub repository '{repo_name}': {create_res.status_code} {clean_err}",
                code="REPO_CREATION_FAILED",
            )

    async def publish_repository(
        self,
        repo_name: str,
        files: List[GeneratedWebsiteFile],
        branch: str = "main",
        commit_message: str = "Deploy website from AI Web Agency",
    ) -> GitHubPublishResult:
        """
        Publishes the validated website files to the target repository using the Git Data API.
        Guarantees non-destructive updates without force-pushing.
        """
        if not self.is_configured:
            raise ProviderConfigurationError("GitHub integration is not configured.")

        # 1. Security screening
        self.validate_files_security(files)

        # 2. Ensure repository exists
        repo_data = await self.ensure_repository(repo_name)
        full_name = repo_data["full_name"]
        repo_html_url = repo_data["html_url"]
        headers = self._headers()

        async with httpx.AsyncClient(timeout=60.0) as client:
            # 3. Get branch ref to determine latest commit SHA
            ref_url = f"{self._api_base_url}/repos/{full_name}/git/refs/heads/{branch}"
            ref_res = await client.get(ref_url, headers=headers)
            base_tree_sha: Optional[str] = None
            parent_commit_sha: Optional[str] = None

            if ref_res.status_code == 200:
                parent_commit_sha = ref_res.json()["object"]["sha"]
                commit_info_url = f"{self._api_base_url}/repos/{full_name}/git/commits/{parent_commit_sha}"
                commit_res = await client.get(commit_info_url, headers=headers)
                if commit_res.status_code == 200:
                    base_tree_sha = commit_res.json()["tree"]["sha"]
            elif ref_res.status_code == 404:
                # If branch doesn't exist, check default branch
                default_branch = repo_data.get("default_branch", "main")
                def_ref_url = f"{self._api_base_url}/repos/{full_name}/git/refs/heads/{default_branch}"
                def_res = await client.get(def_ref_url, headers=headers)
                if def_res.status_code == 200:
                    parent_commit_sha = def_res.json()["object"]["sha"]

            # 4. Create blobs for each file
            tree_entries: List[Dict[str, Any]] = []
            for f in files:
                blob_url = f"{self._api_base_url}/repos/{full_name}/git/blobs"
                b64_content = base64.b64encode(f.content.encode("utf-8")).decode("ascii")
                blob_res = await client.post(
                    blob_url,
                    headers=headers,
                    json={"content": b64_content, "encoding": "base64"},
                )
                if blob_res.status_code not in (200, 201):
                    raise ProviderExecutionError(
                        f"Failed to create blob for {f.path}: {self._redact_message(blob_res.text)}"
                    )
                blob_sha = blob_res.json()["sha"]
                tree_entries.append({
                    "path": f.path.replace("\\", "/").strip().lstrip("/"),
                    "mode": "100644",
                    "type": "blob",
                    "sha": blob_sha,
                })

            # 5. Create new Git Tree
            tree_payload: Dict[str, Any] = {"tree": tree_entries}
            if base_tree_sha:
                tree_payload["base_tree"] = base_tree_sha

            tree_url = f"{self._api_base_url}/repos/{full_name}/git/trees"
            new_tree_res = await client.post(tree_url, headers=headers, json=tree_payload)
            if new_tree_res.status_code not in (200, 201):
                raise ProviderExecutionError(
                    f"Failed to create tree: {self._redact_message(new_tree_res.text)}"
                )
            new_tree_sha = new_tree_res.json()["sha"]

            # 6. Create Commit
            commit_payload: Dict[str, Any] = {
                "message": commit_message,
                "tree": new_tree_sha,
                "parents": [parent_commit_sha] if parent_commit_sha else [],
            }
            commit_url = f"{self._api_base_url}/repos/{full_name}/git/commits"
            new_commit_res = await client.post(commit_url, headers=headers, json=commit_payload)
            if new_commit_res.status_code not in (200, 201):
                raise ProviderExecutionError(
                    f"Failed to create commit: {self._redact_message(new_commit_res.text)}"
                )
            new_commit_sha = new_commit_res.json()["sha"]

            # 7. Update Ref (force=False to prevent accidental overwrites)
            if parent_commit_sha and ref_res.status_code == 200:
                update_ref_url = f"{self._api_base_url}/repos/{full_name}/git/refs/heads/{branch}"
                ref_update_res = await client.patch(
                    update_ref_url,
                    headers=headers,
                    json={"sha": new_commit_sha, "force": False},
                )
                if ref_update_res.status_code not in (200, 201):
                    raise ProviderExecutionError(
                        f"Ref update rejected (force-push prevented): {self._redact_message(ref_update_res.text)}"
                    )
            else:
                create_ref_url = f"{self._api_base_url}/repos/{full_name}/git/refs"
                ref_create_res = await client.post(
                    create_ref_url,
                    headers=headers,
                    json={"ref": f"refs/heads/{branch}", "sha": new_commit_sha},
                )
                if ref_create_res.status_code not in (200, 201):
                    raise ProviderExecutionError(
                        f"Failed to create branch ref: {self._redact_message(ref_create_res.text)}"
                    )

            log.info(
                "github_publish_success",
                repo=full_name,
                branch=branch,
                commit=new_commit_sha,
                files_count=len(files),
            )

            return GitHubPublishResult(
                repo_url=repo_html_url,
                repo_name=full_name,
                branch=branch,
                commit_sha=new_commit_sha,
                commit_message=commit_message,
                published_files_count=len(files),
                is_mock=False,
            )
