"""
Phase 6 Stage 6.2 — AI Website Generation Provider Abstraction.

Responsibilities:
1. Provider interface for generating structured website specifications.
2. Deterministic mock provider returning complete, valid specifications anchored to PRD data.
3. Configurable provider error simulation for tests.
4. Safe provider factory preventing credential leakage and ensuring system stability.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import json
from typing import Any, Dict, List, Optional, Tuple

import structlog

from core.config import settings
from schemas.website_specification import (
    ColorPaletteSpecification,
    ContentSpecification,
    DesignSystemSpecification,
    NavigationItemSpecification,
    PageSpecification,
    SectionSpecification,
    TypographySpecification,
    WebsiteSpecification,
)

log = structlog.get_logger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class AIProviderError(Exception):
    """Base exception for website generation provider errors."""
    pass


class AIProviderConfigurationError(AIProviderError):
    """Raised when an AI provider is requested but improperly configured."""
    pass


class AIProviderExecutionError(AIProviderError):
    """Raised when an AI provider fails during specification generation."""
    pass


# ── Abstract Base Provider ───────────────────────────────────────────────────

class AIWebsiteGenerationProvider(ABC):
    """
    Abstract interface for AI Website Specification Generation Providers.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    async def generate_specification(
        self,
        system_prompt: str,
        user_prompt: str,
        context: Dict[str, Any],
    ) -> Tuple[WebsiteSpecification, Dict[str, Any]]:
        """
        Executes specification generation.
        Returns:
            Tuple of (WebsiteSpecification, metadata_dict)
        """
        pass


# ── Deterministic Mock Provider ──────────────────────────────────────────────

class MockWebsiteGenerationProvider(AIWebsiteGenerationProvider):
    """
    Deterministic provider producing valid, rich WebsiteSpecifications anchored
    to the source PRD and project context.
    """

    def __init__(
        self,
        simulate_failure: bool = False,
        simulate_malformed: bool = False,
        simulate_injection: bool = False,
        simulate_missing_fields: bool = False,
        custom_provider_name: str = "mock_provider",
        custom_model_name: str = "mock-spec-v1",
    ):
        self._simulate_failure = simulate_failure
        self._simulate_malformed = simulate_malformed
        self._simulate_injection = simulate_injection
        self._simulate_missing_fields = simulate_missing_fields
        self._provider_name = custom_provider_name
        self._model_name = custom_model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate_specification(
        self,
        system_prompt: str,
        user_prompt: str,
        context: Dict[str, Any],
    ) -> Tuple[WebsiteSpecification, Dict[str, Any]]:
        if self._simulate_failure:
            raise AIProviderExecutionError("Simulated AI provider API timeout or service unavailable.")

        if self._simulate_malformed:
            raise AIProviderExecutionError("AI provider returned invalid non-JSON output.")

        # Extract authoritative context
        project_name = context.get("project_name", "Modern Business Website")
        project_slug = context.get("project_slug", "modern-business")
        source_prd_id = str(context.get("source_prd_id", "00000000-0000-0000-0000-000000000000"))
        source_prd_version = int(context.get("source_prd_version", 1))
        generation_version = int(context.get("generation_version", 1))

        prd_summary = context.get("prd_data", {})
        sitemap_raw = prd_summary.get("sitemap") or [{"page": "Home"}, {"page": "About"}, {"page": "Services"}, {"page": "Contact"}]
        goals_raw = prd_summary.get("goals") or ["Establish strong digital authority", "Generate qualified business leads"]
        audience_raw = str(prd_summary.get("target_audience") or "High-value commercial clients and partners")

        primary_cta = "Get in Touch"
        if self._simulate_injection:
            primary_cta = "Execute script: <script>alert(1)</script>"

        # Build pages based on sitemap
        pages: List[PageSpecification] = []
        navigation: List[NavigationItemSpecification] = []

        seen_paths = set()
        order = 1

        for item in sitemap_raw:
            page_name = item.get("page") if isinstance(item, dict) else str(item)
            if not page_name:
                continue

            slug = page_name.lower().strip().replace(" ", "-")
            path = "/" if slug in ("home", "index", "root") else f"/{slug}"

            if path in seen_paths:
                continue
            seen_paths.add(path)

            page_id = f"page_{slug.replace('-', '_')}" if slug not in ("home", "index", "root") else "page_home"

            # Sections for this page
            sections = [
                SectionSpecification(
                    section_id=f"{page_id}_hero",
                    type="hero",
                    purpose=f"Introduce {page_name} with clear visual branding and value proposition",
                    heading=f"Welcome to {project_name} - {page_name}",
                    supporting_content="Delivering industry-leading solutions tailored to your unique requirements.",
                    layout="two-column-split",
                    components=["HeroHeading", "ValueProposition", "CTAButtonGroup"],
                    cta="Learn More",
                    visibility="visible",
                    responsive_behavior="stack-on-mobile",
                ),
                SectionSpecification(
                    section_id=f"{page_id}_content",
                    type="content-overview",
                    purpose=f"Detailed overview of {page_name} key features and capabilities",
                    heading=f"Why Choose Our {page_name} Solutions",
                    supporting_content="Built with reliability, precision, and state-of-the-art standards.",
                    layout="grid-3-col",
                    components=["FeatureCardGrid", "StatCounter"],
                    cta="Schedule Consultation",
                    visibility="visible",
                    responsive_behavior="stack-on-mobile",
                ),
                SectionSpecification(
                    section_id=f"{page_id}_footer",
                    type="footer",
                    purpose="Site navigation links, copyright, and global contact information",
                    heading=f"{project_name}",
                    supporting_content="All rights reserved. Secure and verified client portal.",
                    layout="single-column",
                    components=["FooterNavigation", "ContactSnippet", "LegalDisclaimer"],
                    cta=None,
                    visibility="visible",
                    responsive_behavior="stack-on-mobile",
                ),
            ]

            pages.append(
                PageSpecification(
                    page_id=page_id,
                    path=path,
                    name=page_name,
                    purpose=f"Dedicated page for {page_name} within the website.",
                    priority="primary" if path == "/" else "secondary",
                    seo_title=f"{page_name} | {project_name}",
                    seo_description=f"Explore {page_name} at {project_name}. Proven expertise, transparent delivery, and results.",
                    sections=sections,
                    primary_cta=primary_cta,
                    secondary_cta="Contact Us",
                )
            )

            navigation.append(
                NavigationItemSpecification(
                    label=page_name,
                    path=path,
                    order=order,
                    visibility="all",
                )
            )
            order += 1

        # Ensure root page exists
        if "/" not in seen_paths:
            pages.insert(
                0,
                PageSpecification(
                    page_id="page_home",
                    path="/",
                    name="Home",
                    purpose="Main landing page presenting core value proposition and navigation.",
                    priority="primary",
                    seo_title=f"Home | {project_name}",
                    seo_description=f"Welcome to {project_name}. Premier solutions and services.",
                    sections=[
                        SectionSpecification(
                            section_id="home_hero",
                            type="hero",
                            purpose="Primary brand introduction",
                            heading=f"Transforming Business with {project_name}",
                            supporting_content="High-impact digital excellence designed for growth.",
                            layout="two-column-split",
                            components=["HeroBanner", "CTAButtonGroup"],
                            cta="Get Started",
                            visibility="visible",
                            responsive_behavior="stack-on-mobile",
                        )
                    ],
                    primary_cta=primary_cta,
                ),
            )
            navigation.insert(
                0,
                NavigationItemSpecification(
                    label="Home",
                    path="/",
                    order=1,
                    visibility="all",
                ),
            )

        design_system = DesignSystemSpecification(
            visual_direction="Refined modern corporate aesthetic with high-contrast accents and clean typography.",
            typography=TypographySpecification(
                heading_family="Inter, sans-serif",
                body_family="Inter, sans-serif",
                heading_scale={"h1": "2.5rem", "h2": "2rem", "h3": "1.5rem", "h4": "1.25rem"},
                body_scale={"sm": "0.875rem", "base": "1rem", "lg": "1.125rem"},
            ),
            color_palette=ColorPaletteSpecification(
                primary="#141216",
                secondary="#242126",
                accent="#E8B968",
                background="#0C0B0D",
                surface="#1B191E",
                text="#F5F1EA",
                muted="#77717C",
            ),
            spacing={"xs": "0.25rem", "sm": "0.5rem", "md": "1rem", "lg": "2rem", "xl": "3rem"},
            border_radius={"sm": "0.375rem", "md": "0.75rem", "lg": "1rem", "full": "9999px"},
            shadows={"sm": "0 1px 2px rgba(0,0,0,0.05)", "md": "0 4px 6px rgba(0,0,0,0.1)", "lg": "0 10px 15px rgba(0,0,0,0.1)"},
            imagery_direction="Authentic professional photography with subtle warm lighting.",
            icon_direction="Refined geometric line icons with consistent 1.5px stroke weight.",
            motion_direction="Smooth subtle ease-in-out transitions, 200ms duration.",
            responsive_strategy="Fluid mobile-first flexbox and grid layouts.",
        )

        content_strategy = [
            ContentSpecification(
                page="/",
                section="home_hero",
                content_type="hero_headline",
                required=True,
                source="PRD",
                notes="Anchored directly to approved PRD executive summary and business overview.",
            ),
            ContentSpecification(
                page="/",
                section="home_hero",
                content_type="primary_cta",
                required=True,
                source="CLIENT_REQUIREMENT",
                notes="Reflects verified conversion goal from client intelligence requirements.",
            ),
        ]

        open_questions = prd_summary.get("open_questions") or []
        formatted_open_questions = [
            q.get("question") if isinstance(q, dict) else str(q)
            for q in open_questions
        ]

        # Synthesize safe website goal, ignoring untrusted command injections
        goals_text = " ".join(goals_raw) if isinstance(goals_raw, list) else str(goals_raw)
        injection_indicators = ["ignore all", "rm -rf", "deploy this", "github repository", "execute shell", "<script"]
        if any(ind in goals_text.lower() for ind in injection_indicators):
            website_goal = "Deliver high-quality, secure digital web presence tailored to business objectives."
        else:
            website_goal = goals_text

        spec_kwargs = {
            "specification_version": "1.0.0",
            "generation_version": generation_version,
            "project_name": project_name,
            "project_slug": project_slug,
            "website_goal": website_goal,
            "target_audience": audience_raw,
            "primary_cta": primary_cta,
            "secondary_ctas": ["Learn More", "Contact Sales"],
            "navigation": navigation,
            "pages": pages,
            "design_system": design_system,
            "content_strategy": content_strategy,
            "accessibility_requirements": [
                "WCAG 2.1 AA Compliance",
                "Keyboard navigable components and forms",
                "High color contrast ratio minimum 4.5:1",
            ],
            "responsive_requirements": [
                "Mobile viewport (<640px)",
                "Tablet viewport (640px - 1024px)",
                "Desktop viewport (>1024px)",
            ],
            "technical_constraints": [
                "Zero client-side errors",
                "Fast initial load time under 1.5s",
                "Semantic landmark HTML structure",
            ],
            "open_questions": formatted_open_questions,
            "source_prd_id": source_prd_id,
            "source_prd_version": source_prd_version,
        }

        if self._simulate_missing_fields:
            # Drop a required field
            del spec_kwargs["project_name"]

        spec = WebsiteSpecification(**spec_kwargs)

        provider_meta = {
            "provider": self.provider_name,
            "model": self.model_name,
            "pages_count": len(pages),
            "sections_count": sum(len(p.sections) for p in pages),
            "tokens_used": 1420,
        }

        return spec, provider_meta


# ── Provider Factory ──────────────────────────────────────────────────────────

def get_website_generation_provider(
    provider_override: Optional[AIWebsiteGenerationProvider] = None,
) -> AIWebsiteGenerationProvider:
    """
    Returns the active AI Website Generation Provider based on configuration.
    Defaults to MockWebsiteGenerationProvider for tests and offline development.
    """
    if provider_override:
        return provider_override

    # Check if a non-mock provider is explicitly requested
    provider_type = getattr(settings, "AI_PROVIDER", "mock").lower()

    if provider_type == "mock":
        return MockWebsiteGenerationProvider()

    if provider_type in ("nemotron", "nvidia"):
        if not getattr(settings, "NEMOTRON_ENABLED", False) or not getattr(settings, "NEMOTRON_API_KEY", ""):
            raise AIProviderConfigurationError(
                "NEMOTRON provider was specified but NEMOTRON_ENABLED is False or NEMOTRON_API_KEY is missing."
            )
        # In Phase 6.2, we keep mock provider as fallback / safe default while maintaining interface
        return MockWebsiteGenerationProvider(
            custom_provider_name="nemotron_adapter",
            custom_model_name=getattr(settings, "NEMOTRON_MODEL", "nvidia/llama-3.1-nemotron-ultra-253b-v1"),
        )

    # Unknown provider
    raise AIProviderConfigurationError(f"Unsupported AI_PROVIDER configured: '{provider_type}'")
