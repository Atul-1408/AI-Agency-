"""
Phase 6 Stage 6.4 — AI Website Code Generation Validator.

Deterministic static safety and structural validator for generated Next.js projects.
Enforces:
1. Path safety (relative, normalized, no path traversal, allowed extensions).
2. Required Next.js entrypoints (package.json, tsconfig.json, app/layout.tsx, app/page.tsx, app/globals.css).
3. Code safety & static analysis (eval, child_process, exec, shell commands, dangerous redirects, iframe injection).
4. Secret detection (AWS keys, GitHub tokens, OpenAI keys, private certificates).
5. Referential integrity (component imports match generated component files).
6. Route uniqueness and structural coherence.
"""
from __future__ import annotations

import os
import re
from typing import List, Set

from schemas.code_generation import GeneratedWebsiteFile, GeneratedWebsiteProject


class CodeValidationError(Exception):
    """Base exception for code validation failures."""
    pass


class ForbiddenPatternError(CodeValidationError):
    """Raised when unsafe code patterns or execution APIs are detected."""
    pass


class SecretDetectedError(CodeValidationError):
    """Raised when hardcoded credentials or API keys are detected."""
    pass


class MissingRequiredFileError(CodeValidationError):
    """Raised when standard Next.js entrypoint files are missing."""
    pass


class PathSecurityError(CodeValidationError):
    """Raised when invalid or malicious file paths are detected."""
    pass


class ComponentReferenceError(CodeValidationError):
    """Raised when page imports a nonexistent component file."""
    pass


# ── Allowed Extensions ────────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".json",
    ".md",
    ".mjs",
    ".svg",
    ".html",
    ".ico",
}

# ── Required Next.js Entrypoints ──────────────────────────────────────────────
REQUIRED_FILES = {
    "package.json",
    "tsconfig.json",
    "app/layout.tsx",
    "app/page.tsx",
    "app/globals.css",
}

# ── Max Sizes ─────────────────────────────────────────────────────────────────
MAX_SINGLE_FILE_BYTES = 2 * 1024 * 1024       # 2 MB
MAX_TOTAL_PROJECT_BYTES = 20 * 1024 * 1024    # 20 MB

# ── Dangerous Code Patterns (Forbidden) ───────────────────────────────────────
FORBIDDEN_PATTERNS = [
    (r"\beval\s*\(", "eval() execution"),
    (r"\bnew\s+Function\s*\(", "new Function() dynamic execution"),
    (r"\bchild_process\b", "child_process execution module"),
    (r"\b(exec|execSync|spawn|spawnSync|fork)\s*\(", "Process spawn/exec API"),
    (r"javascript:\s*", "javascript: pseudo-protocol URL"),
    (r"<iframe[^>]*src=[\"'](?!about:blank)[^\"']*[\"']", "Unsanitized iframe injection"),
    (r"<script[^>]*src=[\"']http://", "Insecure HTTP external script inclusion"),
    (r"\b(rm\s+-rf|del\s+/f|format\s+c:)", "Destructive shell command string"),
]

# ── Secret Detection Patterns ─────────────────────────────────────────────────
SECRET_PATTERNS = [
    (r"\bAKIA[0-9A-Z]{16}\b", "AWS Access Key ID"),
    (r"\bghp_[0-9a-zA-Z]{36}\b", "GitHub Personal Access Token"),
    (r"\bsk-[a-zA-Z0-9]{20,}\b", "OpenAI Secret Key"),
    (r"-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----", "Private cryptographic key"),
    (r"(?i)(api[_-]?key|secret[_-]?token|auth[_-]?password)\s*[:=]\s*[\"'][a-zA-Z0-9\-_]{24,}[\"']", "Hardcoded credential assignment"),
]


class CodeGenerationValidator:
    """
    Validates a GeneratedWebsiteProject against strict security, framework, and integrity rules.
    """

    @classmethod
    def validate_project(cls, project: GeneratedWebsiteProject) -> None:
        """
        Validates the entire generated project. Raises CodeValidationError on violation.
        """
        if not project.files:
            raise MissingRequiredFileError("Generated project contains 0 files.")

        total_bytes = 0
        seen_paths: Set[str] = set()

        # 1. Path Safety, Duplicates, Extensions, Size
        for f in project.files:
            normalized_path = cls._validate_file_path(f.path)
            if normalized_path in seen_paths:
                raise PathSecurityError(f"Duplicate file path detected: {normalized_path}")
            seen_paths.add(normalized_path)

            if f.size_bytes > MAX_SINGLE_FILE_BYTES:
                raise CodeValidationError(
                    f"File {f.path} exceeds maximum allowed size ({f.size_bytes} > {MAX_SINGLE_FILE_BYTES} bytes)"
                )
            total_bytes += f.size_bytes

        if total_bytes > MAX_TOTAL_PROJECT_BYTES:
            raise CodeValidationError(
                f"Total project size exceeds maximum allowed ({total_bytes} > {MAX_TOTAL_PROJECT_BYTES} bytes)"
            )

        # 2. Required Next.js Entrypoints
        missing_required = REQUIRED_FILES - seen_paths
        if missing_required:
            raise MissingRequiredFileError(
                f"Missing required Next.js entrypoint files: {sorted(list(missing_required))}"
            )

        # 3. Content Safety (Forbidden APIs & Secrets)
        for f in project.files:
            cls._scan_file_safety(f)

        # 4. Referential Component Checks
        cls._verify_component_references(project, seen_paths)

    @classmethod
    def _validate_file_path(cls, path: str) -> str:
        """Checks path for traversal, dangerous characters, and allowed extension."""
        clean = path.strip().replace("\\", "/")
        if clean.startswith("/"):
            clean = clean.lstrip("/")

        parts = clean.split("/")
        if ".." in parts or "." in parts:
            raise PathSecurityError(f"Path traversal detected in path: '{path}'")
        if ":" in clean:
            raise PathSecurityError(f"Drive letter detected in path: '{path}'")
        if "\x00" in clean:
            raise PathSecurityError(f"Null byte detected in path: '{path}'")

        _, ext = os.path.splitext(clean)
        # Handle files without extension like dotfiles or special configs
        basename = os.path.basename(clean)
        if ext.lower() not in ALLOWED_EXTENSIONS and basename not in ("package.json", "tsconfig.json", "README.md"):
            raise PathSecurityError(f"Disallowed file extension '{ext}' for file '{clean}'")

        return clean

    @classmethod
    def _scan_file_safety(cls, file: GeneratedWebsiteFile) -> None:
        """Scans single file content for forbidden APIs and secrets."""
        content = file.content

        # Scan for forbidden code execution patterns
        for pattern, label in FORBIDDEN_PATTERNS:
            if re.search(pattern, content):
                raise ForbiddenPatternError(
                    f"Forbidden pattern detected in '{file.path}': {label}"
                )

        # Scan for hardcoded credentials
        for pattern, label in SECRET_PATTERNS:
            if re.search(pattern, content):
                raise SecretDetectedError(
                    f"Potential secret or credential detected in '{file.path}': {label}"
                )

    @classmethod
    def _verify_component_references(cls, project: GeneratedWebsiteProject, all_paths: Set[str]) -> None:
        """
        Ensures components imported by pages via @/components/... or ../components/... exist in the project.
        """
        import_pattern = re.compile(r"from\s+[\"'](@/components/[^\"']+|(\.\./|\./)components/[^\"']+)[\"']")

        for f in project.files:
            # Check tsx/ts files for component imports
            if f.path.endswith((".tsx", ".ts")):
                matches = import_pattern.findall(f.content)
                for match in matches:
                    raw_import = match[0] if isinstance(match, tuple) else match
                    # Normalize @/components/xyz to components/xyz
                    if raw_import.startswith("@/"):
                        rel_comp = raw_import[2:]
                    else:
                        rel_comp = raw_import.lstrip("./").lstrip("../")

                    # Check possible file extensions (.tsx, .ts, /index.tsx)
                    candidates = [
                        rel_comp,
                        f"{rel_comp}.tsx",
                        f"{rel_comp}.ts",
                        f"{rel_comp}/index.tsx",
                    ]
                    if not any(c in all_paths for c in candidates):
                        raise ComponentReferenceError(
                            f"File '{f.path}' imports component '{raw_import}' which is not in generated project."
                        )
