"""
Phase 6 Stage 6.4 — AI Website Workspace Service.

Manages isolated filesystem build workspaces for generated website code.
Responsibilities:
1. Creates isolated disk workspace anchored in a configured workspace root.
2. Writes generated project files safely with path canonicalization and traversal checks.
3. Computes individual SHA-256 digests and an aggregate deterministic source checksum.
4. Generates structured file manifests.
5. Cleans up temporary or failed workspaces.
6. STRICT GUARANTEE: Never executes shell commands, never runs npm install, never spawns processes.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import uuid

import structlog

from schemas.code_generation import GeneratedWebsiteFile, GeneratedWebsiteProject
from services.code_generation_validator import PathSecurityError

log = structlog.get_logger(__name__)

# Base directory for isolated build workspaces
WORKSPACE_BASE_DIR = os.getenv("AGEN_WORKSPACES_DIR", os.path.join(tempfile.gettempdir(), "agen_workspaces"))


class WebsiteWorkspaceService:
    """Provides safe filesystem workspace management for generated code."""

    @classmethod
    def get_workspace_dir(cls, generation_id: uuid.UUID) -> Path:
        """Returns the isolated workspace directory path for a code generation."""
        return Path(WORKSPACE_BASE_DIR).resolve() / str(generation_id)

    @classmethod
    def create_workspace(cls, generation_id: uuid.UUID) -> Path:
        """Creates the workspace directory if it doesn't already exist."""
        ws_dir = cls.get_workspace_dir(generation_id)
        ws_dir.mkdir(parents=True, exist_ok=True)
        return ws_dir

    @classmethod
    def write_project_files(
        cls,
        generation_id: uuid.UUID,
        project: GeneratedWebsiteProject,
    ) -> Tuple[Path, str, List[Dict[str, Any]]]:
        """
        Safely writes all files of a GeneratedWebsiteProject into the isolated workspace.

        Returns:
            Tuple of:
            - workspace directory Path
            - aggregate SHA-256 source checksum
            - list of manifest file summaries
        """
        ws_dir = cls.create_workspace(generation_id)
        resolved_root = ws_dir.resolve()

        file_manifest: List[Dict[str, Any]] = []

        # Sort files deterministically by path for consistent aggregate checksum
        sorted_files = sorted(project.files, key=lambda f: f.path)
        hasher = hashlib.sha256()

        for f in sorted_files:
            # Clean and normalize path
            clean_rel = f.path.strip().replace("\\", "/").lstrip("/")
            target_path = (ws_dir / clean_rel).resolve()

            # Prevent directory traversal outside the isolated workspace
            try:
                if os.path.commonpath([str(target_path), str(resolved_root)]) != str(resolved_root):
                    raise PathSecurityError(f"File path '{f.path}' attempts directory escape.")
            except ValueError as exc:
                raise PathSecurityError(f"Invalid path traversal attempt: '{f.path}'") from exc

            # Ensure parent directories exist
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Write content with UTF-8 encoding
            content_bytes = f.content.encode("utf-8")
            target_path.write_bytes(content_bytes)

            file_checksum = hashlib.sha256(content_bytes).hexdigest()
            f.checksum = file_checksum
            f.size_bytes = len(content_bytes)

            # Accumulate into aggregate checksum
            hasher.update(clean_rel.encode("utf-8"))
            hasher.update(b"\x00")
            hasher.update(file_checksum.encode("utf-8"))
            hasher.update(b"\n")

            file_manifest.append({
                "path": clean_rel,
                "size_bytes": len(content_bytes),
                "checksum": file_checksum,
                "file_type": f.file_type,
            })

        aggregate_checksum = hasher.hexdigest()

        # Write manifest.json into the workspace root
        manifest_data = {
            "generation_id": str(generation_id),
            "framework": project.framework,
            "language": project.language,
            "package_manager": project.package_manager,
            "source_checksum": aggregate_checksum,
            "file_count": len(sorted_files),
            "entrypoints": project.entrypoints,
            "routes": project.routes,
            "components": project.components,
            "files": file_manifest,
        }
        manifest_path = ws_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        log.info(
            "workspace_files_written",
            generation_id=str(generation_id),
            file_count=len(sorted_files),
            checksum=aggregate_checksum,
        )

        return ws_dir, aggregate_checksum, file_manifest

    @classmethod
    def read_manifest(cls, generation_id: uuid.UUID) -> Optional[Dict[str, Any]]:
        """Reads the manifest.json file from the workspace if present."""
        ws_dir = cls.get_workspace_dir(generation_id)
        manifest_path = ws_dir / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    @classmethod
    def read_file(cls, generation_id: uuid.UUID, relative_path: str) -> Optional[str]:
        """Safely reads a single file from the isolated workspace."""
        ws_dir = cls.get_workspace_dir(generation_id)
        resolved_root = ws_dir.resolve()

        clean_rel = relative_path.strip().replace("\\", "/").lstrip("/")
        target_path = (ws_dir / clean_rel).resolve()

        try:
            if os.path.commonpath([str(target_path), str(resolved_root)]) != str(resolved_root):
                return None
        except ValueError:
            return None

        if not target_path.exists() or not target_path.is_file():
            return None

        try:
            return target_path.read_text(encoding="utf-8")
        except Exception:
            return None

    @classmethod
    def cleanup_workspace(cls, generation_id: uuid.UUID) -> bool:
        """Removes the workspace directory and all contained files."""
        ws_dir = cls.get_workspace_dir(generation_id)
        if ws_dir.exists():
            try:
                shutil.rmtree(ws_dir)
                log.info("workspace_cleaned", generation_id=str(generation_id))
                return True
            except Exception as exc:
                log.warning("workspace_cleanup_failed", generation_id=str(generation_id), error=str(exc))
                return False
        return False

    @classmethod
    def get_preview_workspace_dir(cls, project_id: uuid.UUID, preview_id: uuid.UUID) -> Path:
        """Returns the isolated preview workspace directory path."""
        return Path(WORKSPACE_BASE_DIR).resolve() / "previews" / str(project_id) / str(preview_id)

    @classmethod
    def get_version_workspace_dir(cls, project_id: uuid.UUID, version: int) -> Path:
        """Returns the isolated workspace directory path for a specific version."""
        return Path(WORKSPACE_BASE_DIR).resolve() / "versions" / str(project_id) / f"v{version}"

    @classmethod
    def copy_directory(cls, src_dir: Path, dst_dir: Path) -> None:
        """Safely copies all files from src_dir to dst_dir, replacing dst_dir contents."""
        dst_dir.mkdir(parents=True, exist_ok=True)
        for item in src_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(src_dir)
                target_file = dst_dir / rel_path
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target_file)

    @classmethod
    def read_project_from_dir(cls, ws_dir: Path) -> GeneratedWebsiteProject:
        """Reconstitutes a GeneratedWebsiteProject from an existing workspace directory."""
        manifest: Optional[Dict[str, Any]] = None
        manifest_path = ws_dir / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        files: List[GeneratedWebsiteFile] = []
        for item in ws_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(ws_dir).as_posix()
                if rel_path == "manifest.json":
                    continue
                content = item.read_text(encoding="utf-8", errors="replace")
                ext = item.suffix.lstrip(".") or "txt"
                content_bytes = content.encode("utf-8")
                checksum = hashlib.sha256(content_bytes).hexdigest()
                files.append(GeneratedWebsiteFile(
                    path=rel_path,
                    content=content,
                    file_type=ext,
                    checksum=checksum,
                    size_bytes=len(content_bytes),
                ))

        routes = manifest.get("routes", []) if manifest else ["/"]
        components = manifest.get("components", []) if manifest else []
        entrypoints = manifest.get("entrypoints", []) if manifest else ["app/page.tsx", "app/layout.tsx"]

        return GeneratedWebsiteProject(
            framework=manifest.get("framework", "nextjs") if manifest else "nextjs",
            language=manifest.get("language", "typescript") if manifest else "typescript",
            package_manager=manifest.get("package_manager", "npm") if manifest else "npm",
            files=files,
            entrypoints=entrypoints,
            routes=routes,
            components=components,
            assets=manifest.get("assets", []) if manifest else [],
            metadata=manifest.get("metadata", {}) if manifest else {},
        )
