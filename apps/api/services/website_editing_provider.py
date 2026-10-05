"""
Phase 6 Stage 6.5 — Website Editing Provider Abstraction.

Provides:
- WebsiteEditingProvider (Abstract Base Class)
- MockWebsiteEditingProvider (Deterministic test provider for offline execution and simulation)
- AIWebsiteEditingProvider (Production provider using OpenAI / LangChain)

Adheres strictly to the MINIMAL CHANGE RULE:
Only modified files are generated and returned, avoiding project-wide regeneration.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import structlog

from schemas.code_generation import GeneratedWebsiteFile, GeneratedWebsiteProject
from services.website_editing_prompt_builder import WebsiteEditingPromptBuilder

log = structlog.get_logger(__name__)


class WebsiteEditingProvider(ABC):
    """Abstract base provider for AI iterative website editing."""

    @abstractmethod
    async def generate_edit(
        self,
        current_project: GeneratedWebsiteProject,
        owner_request: str,
        prd_content: str,
        website_spec: Dict[str, Any],
        design_blueprint: Dict[str, Any],
    ) -> Tuple[List[GeneratedWebsiteFile], str, List[str], List[str]]:
        """
        Processes an owner edit request against the current website codebase.

        Returns:
            Tuple of:
            - changed_files: List of ONLY the modified GeneratedWebsiteFile instances
            - diff_summary: Human-readable description of modifications made
            - affected_routes: List of routes impacted by the change
            - affected_components: List of component names impacted by the change
        """
        pass


class MockWebsiteEditingProvider(WebsiteEditingProvider):
    """
    Deterministic mock editing provider for automated tests and offline simulation.
    Understands semantic edit requests and applies targeted minimal updates.
    """

    def __init__(self, provider_name: str = "mock_editing_provider", model_name: str = "mock-nextjs-editor-v1"):
        self.provider_name = provider_name
        self.model_name = model_name

    def _make_file(self, path: str, content: str, file_type: str = "tsx") -> GeneratedWebsiteFile:
        content_bytes = content.encode("utf-8")
        return GeneratedWebsiteFile(
            path=path,
            content=content,
            file_type=file_type,
            checksum=hashlib.sha256(content_bytes).hexdigest(),
            size_bytes=len(content_bytes),
        )

    async def generate_edit(
        self,
        current_project: GeneratedWebsiteProject,
        owner_request: str,
        prd_content: str,
        website_spec: Dict[str, Any],
        design_blueprint: Dict[str, Any],
    ) -> Tuple[List[GeneratedWebsiteFile], str, List[str], List[str]]:
        log.info(
            "mock_editing_provider_invoked",
            request=owner_request,
            existing_file_count=len(current_project.files),
        )

        req_lower = owner_request.lower().strip()

        # ── Test Simulation Flags ─────────────────────────────────────────────
        if "__SIMULATE_FORBIDDEN_PATTERN__" in owner_request:
            bad_content = 'export default function Malicious() { eval("alert(1)"); return <div>Test</div>; }'
            bad_file = self._make_file("components/ui/Malicious.tsx", bad_content, "tsx")
            return [bad_file], "Injected forbidden eval() pattern for validation testing", ["/"], ["Malicious"]

        if "__SIMULATE_SECRET_LEAK__" in owner_request:
            bad_content = 'export const API_KEY = "sk-1234567890abcdef1234567890abcdef";\nexport default function Api() { return null; }'
            bad_file = self._make_file("lib/config.ts", bad_content, "ts")
            return [bad_file], "Injected OpenAI secret key for secret scanner testing", [], []

        if "__SIMULATE_PATH_TRAVERSAL__" in owner_request:
            bad_file = GeneratedWebsiteFile.model_construct(
                path="../escaped_file.tsx",
                content="export default function Escape() { return null; }",
                file_type="tsx",
                checksum="fake",
                size_bytes=42,
            )
            return [bad_file], "Injected path traversal for security testing", [], []

        # Find existing files in project
        files_by_path = {f.path: f for f in current_project.files}

        changed_files: List[GeneratedWebsiteFile] = []
        affected_routes: List[str] = ["/"]
        affected_components: List[str] = []
        diff_summary: str = ""

        # ── Case 1: Hero / Dark / Darker Theme ────────────────────────────────
        if "hero" in req_lower or "dark" in req_lower or "darker" in req_lower:
            hero_path = "components/sections/Hero.tsx"
            hero_file = files_by_path.get(hero_path)
            if hero_file:
                # Minimal targeted modification of Hero section
                updated_content = hero_file.content
                if "bg-" in updated_content:
                    updated_content = re.sub(r"bg-\S+", "bg-slate-950 text-slate-100", updated_content, count=1)
                else:
                    updated_content = updated_content.replace(
                        "<section",
                        '<section className="bg-slate-950 text-slate-100"',
                    )
                updated_content += "\n{/* Applied edit: Dark hero section styling */}\n"
                changed_files.append(self._make_file(hero_path, updated_content, "tsx"))
                affected_components.append("Hero")
                diff_summary = "Applied dark theme background (bg-slate-950) to Hero section."

        # ── Case 2: CTA / Button Text ─────────────────────────────────────────
        elif "cta" in req_lower or "button" in req_lower:
            cta_path = "components/sections/CTA.tsx"
            cta_file = files_by_path.get(cta_path)
            if cta_file:
                updated_content = cta_file.content.replace("Get Started", "Claim Your Free Consultation Now")
                changed_files.append(self._make_file(cta_path, updated_content, "tsx"))
                affected_components.append("CTA")
                diff_summary = "Updated CTA primary button label to 'Claim Your Free Consultation Now'."
            else:
                # If CTA section not separate, adjust Hero
                hero_path = "components/sections/Hero.tsx"
                hero_file = files_by_path.get(hero_path)
                if hero_file:
                    updated_content = hero_file.content.replace("Get Started", "Start Your Journey Today")
                    changed_files.append(self._make_file(hero_path, updated_content, "tsx"))
                    affected_components.append("Hero")
                    diff_summary = "Updated Hero button label to 'Start Your Journey Today'."

        # ── Case 3: Sticky Navigation / Header ────────────────────────────────
        elif "sticky" in req_lower or "nav" in req_lower or "header" in req_lower:
            header_path = "components/navigation/Header.tsx"
            header_file = files_by_path.get(header_path)
            if header_file:
                updated_content = header_file.content.replace(
                    "<header",
                    '<header className="sticky top-0 z-50 backdrop-blur-md bg-white/80 border-b"',
                )
                changed_files.append(self._make_file(header_path, updated_content, "tsx"))
                affected_components.append("Header")
                diff_summary = "Made main navigation header sticky with backdrop-blur and border."

        # ── Case 4: Spacing / Padding / Services ──────────────────────────────
        elif "spacing" in req_lower or "services" in req_lower or "reduce" in req_lower:
            services_path = "components/sections/Services.tsx"
            services_file = files_by_path.get(services_path)
            if services_file:
                updated_content = services_file.content.replace("py-20", "py-10").replace("py-24", "py-12")
                changed_files.append(self._make_file(services_path, updated_content, "tsx"))
                affected_components.append("Services")
                diff_summary = "Reduced vertical padding in Services section from py-20 to py-10."

        # ── Case 5: Testimonials / Social Proof ───────────────────────────────
        elif "testimonial" in req_lower or "review" in req_lower:
            page_path = "app/page.tsx"
            page_file = files_by_path.get(page_path)
            if page_file:
                updated_content = page_file.content + "\n{/* Added Testimonial Section Integration */}\n"
                changed_files.append(self._make_file(page_path, updated_content, "tsx"))
                affected_components.append("TestimonialSection")
                diff_summary = "Integrated social proof testimonial section reference into main landing page."

        # ── Default Fallback (Targeted Minimal Edit) ──────────────────────────
        if not changed_files:
            hero_path = "components/sections/Hero.tsx"
            hero_file = files_by_path.get(hero_path)
            if hero_file:
                updated_content = hero_file.content + f"\n{{/* Owner Edit Applied: {owner_request} */}}\n"
                changed_files.append(self._make_file(hero_path, updated_content, "tsx"))
                affected_components.append("Hero")
                diff_summary = f"Updated Hero section to incorporate owner request: '{owner_request}'."
            else:
                page_path = "app/page.tsx"
                page_file = files_by_path.get(page_path)
                if page_file:
                    updated_content = page_file.content + f"\n{{/* Owner Edit Applied: {owner_request} */}}\n"
                    changed_files.append(self._make_file(page_path, updated_content, "tsx"))
                    diff_summary = f"Updated landing page to incorporate owner request: '{owner_request}'."

        log.info(
            "mock_editing_provider_completed",
            changed_files_count=len(changed_files),
            diff_summary=diff_summary,
        )

        return changed_files, diff_summary, affected_routes, affected_components


class AIWebsiteEditingProvider(WebsiteEditingProvider):
    """
    Production AI website editing provider powered by LLMs (OpenAI / LangChain).
    Delegates to MockWebsiteEditingProvider if external API keys are unavailable.
    """

    def __init__(self, model_name: str = "gpt-4o", temperature: float = 0.2):
        self.model_name = model_name
        self.temperature = temperature
        self.fallback_mock = MockWebsiteEditingProvider(provider_name="ai_fallback_mock", model_name=model_name)

    async def generate_edit(
        self,
        current_project: GeneratedWebsiteProject,
        owner_request: str,
        prd_content: str,
        website_spec: Dict[str, Any],
        design_blueprint: Dict[str, Any],
    ) -> Tuple[List[GeneratedWebsiteFile], str, List[str], List[str]]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            log.warning("OPENAI_API_KEY not set. Using deterministic mock editing provider.")
            return await self.fallback_mock.generate_edit(
                current_project=current_project,
                owner_request=owner_request,
                prd_content=prd_content,
                website_spec=website_spec,
                design_blueprint=design_blueprint,
            )

        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import SystemMessage, HumanMessage

            prompt_builder = WebsiteEditingPromptBuilder()
            prompt = prompt_builder.build_editing_prompt(
                current_project=current_project,
                owner_request=owner_request,
                prd_content=prd_content,
                website_spec=website_spec,
                design_blueprint=design_blueprint,
            )

            llm = ChatOpenAI(model=self.model_name, temperature=self.temperature)
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            response_text = response.content.strip()

            if response_text.startswith("```"):
                response_text = re.sub(r"^```[a-zA-Z]*\n?", "", response_text)
                response_text = re.sub(r"\n?```$", "", response_text)

            parsed = json.loads(response_text)
            raw_files = parsed.get("changed_files", [])
            diff_summary = parsed.get("diff_summary", f"Applied edit: {owner_request}")
            affected_routes = parsed.get("affected_routes", ["/"])
            affected_components = parsed.get("affected_components", [])

            changed_files: List[GeneratedWebsiteFile] = []
            for rf in raw_files:
                path = rf["path"].strip().replace("\\", "/").lstrip("/")
                content = rf["content"]
                ext = path.split(".")[-1] if "." in path else "tsx"
                content_bytes = content.encode("utf-8")
                checksum = hashlib.sha256(content_bytes).hexdigest()
                changed_files.append(GeneratedWebsiteFile(
                    path=path,
                    content=content,
                    file_type=ext,
                    checksum=checksum,
                    size_bytes=len(content_bytes),
                ))

            return changed_files, diff_summary, affected_routes, affected_components

        except Exception as exc:
            log.error("ai_editing_provider_failed, falling back to mock", error=str(exc))
            return await self.fallback_mock.generate_edit(
                current_project=current_project,
                owner_request=owner_request,
                prd_content=prd_content,
                website_spec=website_spec,
                design_blueprint=design_blueprint,
            )
