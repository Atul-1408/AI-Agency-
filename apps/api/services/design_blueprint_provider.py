"""
Phase 6 Stage 6.3 — AI Design System & Site Architecture Blueprint Provider.

Responsibilities:
1. Provider interface for generating structured Design Blueprints from WebsiteSpecification.
2. Deterministic mock provider producing implementation-ready blueprints anchored to Phase 6.2 output.
3. Test simulation flags for provider failures, malformed output, and invalid component references.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

import structlog

from core.config import settings
from schemas.design_blueprint import (
    AccessibilityBlueprint,
    AssetRequirement,
    BlueprintContentMapping,
    ColorTokens,
    ComponentSpecification,
    DesignTokens,
    InteractionSpecification,
    PageBlueprint,
    ResponsiveBreakpoint,
    SectionBlueprint,
    SiteArchitecture,
    TypographyTokens,
    WebsiteDesignBlueprint,
)
from schemas.website_specification import WebsiteSpecification
from services.website_generator_provider import (
    AIProviderConfigurationError,
    AIProviderError,
    AIProviderExecutionError,
)

log = structlog.get_logger(__name__)


# ── Abstract Base Provider ───────────────────────────────────────────────────

class AIDesignBlueprintProvider(ABC):
    """Abstract interface for AI Design Blueprint Providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    async def generate_blueprint(
        self,
        system_prompt: str,
        user_prompt: str,
        context: Dict[str, Any],
    ) -> Tuple[WebsiteDesignBlueprint, Dict[str, Any]]:
        pass


# ── Deterministic Mock Provider ──────────────────────────────────────────────

class MockDesignBlueprintProvider(AIDesignBlueprintProvider):
    """
    Deterministic mock provider synthesizing complete, implementation-ready design blueprints
    anchored to validated WebsiteSpecification and PRD context.
    """

    def __init__(
        self,
        simulate_failure: bool = False,
        simulate_malformed: bool = False,
        simulate_missing_fields: bool = False,
        simulate_invalid_ref: bool = False,
        custom_provider_name: str = "mock_design_provider",
        custom_model_name: str = "mock-blueprint-v1",
    ):
        self._simulate_failure = simulate_failure
        self._simulate_malformed = simulate_malformed
        self._simulate_missing_fields = simulate_missing_fields
        self._simulate_invalid_ref = simulate_invalid_ref
        self._provider_name = custom_provider_name
        self._model_name = custom_model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate_blueprint(
        self,
        system_prompt: str,
        user_prompt: str,
        context: Dict[str, Any],
    ) -> Tuple[WebsiteDesignBlueprint, Dict[str, Any]]:
        if self._simulate_failure:
            raise AIProviderExecutionError("Simulated AI design blueprint provider timeout.")

        if self._simulate_malformed:
            raise AIProviderExecutionError("AI provider returned invalid non-JSON output.")

        # Extract context
        spec_dict = context.get("specification", {})
        spec = WebsiteSpecification.model_validate(spec_dict)
        blueprint_version = int(context.get("blueprint_version", 1))
        source_generation_id = str(context.get("source_generation_id", ""))
        source_generation_version = int(context.get("source_generation_version", 1))

        # 1. Design Tokens (derived from spec design system)
        colors = ColorTokens(
            primary=spec.design_system.color_palette.primary,
            secondary=spec.design_system.color_palette.secondary,
            accent=spec.design_system.color_palette.accent,
            background=spec.design_system.color_palette.background,
            surface=spec.design_system.color_palette.surface,
            surface_elevated="#201D24",
            text=spec.design_system.color_palette.text,
            text_muted=spec.design_system.color_palette.muted,
            border="#242126",
            success="#39C98A",
            warning="#E8B968",
            error="#F87171",
        )

        typography = TypographyTokens(
            heading_font=spec.design_system.typography.heading_family,
            body_font=spec.design_system.typography.body_family,
            mono_font="ui-monospace, SFMono-Regular, Menlo, monospace",
            heading_weights=["600", "700", "800"],
            body_weights=["400", "500"],
            scale={
                "xs": "0.75rem",
                "sm": "0.875rem",
                "base": "1rem",
                "lg": "1.125rem",
                "xl": "1.25rem",
                "2xl": "1.5rem",
                "3xl": "2rem",
                "4xl": "2.5rem",
            },
        )

        design_tokens = DesignTokens(
            colors=colors,
            typography=typography,
            spacing=spec.design_system.spacing or {
                "xs": "0.25rem", "sm": "0.5rem", "md": "1rem", "lg": "1.5rem", "xl": "2rem", "2xl": "3rem", "3xl": "4rem"
            },
            radius=spec.design_system.border_radius or {
                "sm": "0.25rem", "md": "0.5rem", "lg": "0.75rem", "xl": "1rem", "full": "9999px"
            },
            shadows=spec.design_system.shadows or {
                "sm": "0 1px 2px rgba(0,0,0,0.05)", "md": "0 4px 6px rgba(0,0,0,0.1)", "lg": "0 10px 15px rgba(0,0,0,0.1)"
            },
            container={"max_width": "1280px", "gutters": "1.5rem"},
        )

        # 2. Responsive Breakpoint System
        responsive_breakpoints = [
            ResponsiveBreakpoint(
                name="mobile",
                min_width="0px",
                layout_behavior="Single-column vertical stack with full-bleed touch targets",
                typography_behavior="Scaled down headings (-15%), body text at 1rem",
                spacing_behavior="Compact spacing scale (base 0.75rem)",
                navigation_behavior="Collapsible hamburger modal navigation",
                component_behavior="Cards and grids collapse to 100% width",
            ),
            ResponsiveBreakpoint(
                name="tablet",
                min_width="640px",
                layout_behavior="Two-column responsive grid with standard margins",
                typography_behavior="Standard baseline typography scale",
                spacing_behavior="Medium spacing scale (base 1rem)",
                navigation_behavior="Semi-expanded header navigation with icon triggers",
                component_behavior="Cards display in 2-column grid layout",
            ),
            ResponsiveBreakpoint(
                name="desktop",
                min_width="1024px",
                layout_behavior="Multi-column grid up to 4 columns",
                typography_behavior="Full desktop typography scale with prominent headings",
                spacing_behavior="Spacious comfortable padding scale (base 1.5rem)",
                navigation_behavior="Fully expanded horizontal navigation with CTA button",
                component_behavior="Cards display in 3 or 4 columns with hover states",
            ),
            ResponsiveBreakpoint(
                name="wide",
                min_width="1280px",
                layout_behavior="Max-width constrained container (1280px) centered with gutter padding",
                typography_behavior="Maximum scale typography",
                spacing_behavior="Generous breathing room and section separators",
                navigation_behavior="Horizontal navigation with brand emblem",
                component_behavior="Full-width visual fidelity with max-width content bounds",
            ),
        ]

        # 3. Component Taxonomy
        component_taxonomy = [
            ComponentSpecification(
                component_id="comp_layout_container",
                component_name="LayoutContainer",
                category="LAYOUT",
                purpose="Centers page content with responsive padding and max-width boundaries.",
                variants=["standard", "fluid", "narrow"],
                required_props=["children"],
                optional_props=["className", "maxWidth"],
                accessibility_requirements=["Semantic landmark division"],
                responsive_behavior="Applies responsive container gutters",
                allowed_usage="Root wrapper for page sections",
            ),
            ComponentSpecification(
                component_id="comp_header_nav",
                component_name="HeaderNavigation",
                category="NAVIGATION",
                purpose="Primary site header with logo, links, and action button.",
                variants=["sticky", "transparent", "solid"],
                required_props=["logo", "links"],
                optional_props=["ctaText", "ctaHref"],
                accessibility_requirements=["<nav> landmark with aria-label='Main Navigation'"],
                responsive_behavior="Switches to mobile drawer below 1024px",
                allowed_usage="Global site header",
            ),
            ComponentSpecification(
                component_id="comp_hero_banner",
                component_name="HeroBanner",
                category="CONTENT",
                purpose="High-impact page introduction with headline, subcopy, and primary CTA.",
                variants=["split", "centered", "minimal"],
                required_props=["heading", "subheading"],
                optional_props=["primaryCta", "secondaryCta", "badge"],
                accessibility_requirements=["Single H1 per page", "Accessible button contrast"],
                responsive_behavior="Stacks text and visual vertically on mobile",
                allowed_usage="Top section on landing and marketing pages",
            ),
            ComponentSpecification(
                component_id="comp_feature_card",
                component_name="FeatureCard",
                category="CONTENT",
                purpose="Highlights a specific service, capability, or benefit with icon.",
                variants=["card", "outlined", "flat"],
                required_props=["title", "description"],
                optional_props=["icon", "linkText", "href"],
                accessibility_requirements=["Proper heading level H3", "Keyboard focusable link"],
                responsive_behavior="Flex items collapse to full width on mobile",
                allowed_usage="Features, services, and overview sections",
            ),
            ComponentSpecification(
                component_id="comp_cta_button",
                component_name="CTAButton",
                category="CTA",
                purpose="Primary interactive action button with clear visual hierarchy.",
                variants=["primary", "secondary", "ghost", "accent"],
                required_props=["label"],
                optional_props=["href", "onClick", "icon", "disabled"],
                accessibility_requirements=["Visible focus ring", "aria-disabled when inactive"],
                responsive_behavior="Full-width on mobile viewports",
                allowed_usage="All conversion touchpoints",
            ),
            ComponentSpecification(
                component_id="comp_stat_counter",
                component_name="StatCounter",
                category="DATA",
                purpose="Displays numerical credibility metric with label.",
                variants=["default", "large"],
                required_props=["value", "label"],
                optional_props=["prefix", "suffix"],
                accessibility_requirements=["Screen reader aria-label with full descriptive metric"],
                responsive_behavior="Grid wraps to 2-column on mobile",
                allowed_usage="Proof points and trust sections",
            ),
            ComponentSpecification(
                component_id="comp_footer",
                component_name="FooterNavigation",
                category="FOOTER",
                purpose="Global site footer containing legal links, copyright, and sitemap.",
                variants=["multi-column", "compact"],
                required_props=["brandName", "copyrightYear"],
                optional_props=["columns", "socialLinks"],
                accessibility_requirements=["<footer> landmark", "Accessible link colors"],
                responsive_behavior="Columns stack vertically on mobile",
                allowed_usage="Global site footer",
            ),
        ]

        # 4. Convert Pages and Sections into Implementation Blueprints
        pages: List[PageBlueprint] = []
        for p in spec.pages:
            section_blueprints: List[SectionBlueprint] = []
            for s in p.sections:
                comp_refs = ["comp_layout_container"]
                if "hero" in s.type.lower():
                    comp_refs.extend(["comp_hero_banner", "comp_cta_button"])
                elif "footer" in s.type.lower():
                    comp_refs.append("comp_footer")
                else:
                    comp_refs.extend(["comp_feature_card", "comp_cta_button"])

                if self._simulate_invalid_ref:
                    comp_refs.append("comp_nonexistent_reference_xyz")

                section_blueprints.append(
                    SectionBlueprint(
                        section_id=s.section_id,
                        section_type=s.type,
                        purpose=s.purpose,
                        component_refs=comp_refs,
                        content_refs=[f"content_{s.section_id}"],
                        layout=s.layout or "single-column",
                        alignment="center" if "hero" in s.type.lower() else "left",
                        spacing="lg" if "hero" in s.type.lower() else "md",
                        responsive_behavior=s.responsive_behavior or "stack-on-mobile",
                        visual_priority="high" if "hero" in s.type.lower() else "medium",
                        accessibility=f"Accessible section with semantic H2 heading '{s.heading}'",
                        interaction="hover_elevate" if "feature" in s.type.lower() else "none",
                    )
                )

            pages.append(
                PageBlueprint(
                    page_id=p.page_id,
                    route=p.path,
                    name=p.name,
                    purpose=p.purpose,
                    layout_type="marketing-layout" if p.path == "/" else "standard-layout",
                    section_order=[sb.section_id for sb in section_blueprints],
                    sections=section_blueprints,
                    component_refs=["comp_header_nav", "comp_footer"],
                    navigation_refs=[p.path],
                    seo={"title": p.seo_title, "description": p.seo_description},
                    responsive_rules=[
                        "Maintain H1 visibility above the mobile fold",
                        "Preserve 48px minimum touch targets on mobile",
                    ],
                    accessibility_rules=[
                        "Skip to main content link supported",
                        "Sequential heading hierarchy (H1 -> H2 -> H3)",
                    ],
                )
            )

        # 5. Site Architecture
        site_architecture = SiteArchitecture(
            root="/",
            pages=[p.path for p in spec.pages],
            navigation=[{"label": n.label, "path": n.path, "order": n.order} for n in spec.navigation],
            footer={"brand": spec.project_name, "links": [n.path for n in spec.navigation]},
            global_components=["comp_header_nav", "comp_footer"],
            page_dependencies={p.path: ["comp_header_nav", "comp_footer"] for p in spec.pages},
        )

        # 6. Asset Requirements (Descriptive only — NO downloading)
        asset_requirements = [
            AssetRequirement(
                asset_id="asset_brand_logo",
                type="LOGO",
                purpose="Primary header logo emblem and wordmark",
                page="/",
                section="header",
                required=True,
                source="CLIENT_ASSET",
                dimensions="240x60",
                aspect_ratio="4:1",
                accessibility_alt_requirement=f"{spec.project_name} Official Logo",
                placeholder_allowed=True,
            ),
            AssetRequirement(
                asset_id="asset_hero_graphic",
                type="IMAGE",
                purpose="Visual hero graphic supporting value proposition",
                page="/",
                section="home_hero",
                required=False,
                source="STOCK_CURATED",
                dimensions="1200x800",
                aspect_ratio="3:2",
                accessibility_alt_requirement=f"Professional demonstration representing {spec.project_name}",
                placeholder_allowed=True,
            ),
        ]

        # 7. Interaction Specifications (NO JavaScript code)
        interactions = [
            InteractionSpecification(
                interaction_id="interact_button_hover",
                trigger="hover",
                behavior="Subtle brightness lift (+10%) and scale (1.02)",
                duration="150ms",
                reduced_motion_behavior="Color shift only (no scale)",
                accessibility_behavior="Matching high-contrast outline on keyboard focus",
            ),
            InteractionSpecification(
                interaction_id="interact_card_focus",
                trigger="focus",
                behavior="Elevated surface border highlight and distinct 2px focus ring",
                duration="200ms",
                reduced_motion_behavior="Instant border color change",
                accessibility_behavior="Clear 3:1 focus indicator contrast against surface background",
            ),
            InteractionSpecification(
                interaction_id="interact_nav_drawer",
                trigger="modal",
                behavior="Smooth fade and slide-in from right edge",
                duration="250ms",
                reduced_motion_behavior="Instant visibility toggle",
                accessibility_behavior="Focus trapped within drawer until closed; Escape key closes",
            ),
        ]

        # 8. Accessibility Blueprint
        accessibility = AccessibilityBlueprint(
            keyboard_navigation="Complete tab order traversing skip link, header navigation, section links, and footer.",
            focus_behavior="Unambiguous 2px focus indicator on all interactive elements (#E8B968).",
            semantic_structure="Valid HTML5 landmarks (<header>, <nav>, <main>, <section>, <footer>).",
            heading_hierarchy="Strict single H1 per page, sequential H2 section headers, nested H3 subcomponents.",
            form_labels="Explicitly bound <label> elements for all form fields with aria-describedby for validation hints.",
            alt_text_requirements="Meaningful descriptive alt text for informative imagery; decorative images use alt=''.",
            color_contrast_requirement="Strict WCAG 2.1 AA 4.5:1 text-to-background contrast ratio across all palettes.",
            reduced_motion_behavior="Disable transform scaling, sliding transitions, and parallax when prefers-reduced-motion is active.",
            screen_reader_considerations="Dynamic announcements for status updates via aria-live='polite'; aria-hidden for icons.",
        )

        # 9. Content Mapping
        content_mapping = [
            BlueprintContentMapping(
                page=cs.page,
                section=cs.section,
                content_type=cs.content_type,
                required=cs.required,
                status="CONFIRMED" if cs.source in ("PRD", "CLIENT_REQUIREMENT") else "GENERATED_DRAFT",
                source=cs.source,
                notes=cs.notes or "Mapped directly from Phase 6.2 content strategy.",
            )
            for cs in spec.content_strategy
        ]

        blueprint_kwargs = {
            "blueprint_version": blueprint_version,
            "source_generation_id": source_generation_id,
            "source_generation_version": source_generation_version,
            "project_name": spec.project_name,
            "project_slug": spec.project_slug,
            "design_tokens": design_tokens,
            "responsive_breakpoints": responsive_breakpoints,
            "component_taxonomy": component_taxonomy,
            "pages": pages,
            "site_architecture": site_architecture,
            "asset_requirements": asset_requirements,
            "interactions": interactions,
            "accessibility": accessibility,
            "content_mapping": content_mapping,
            "implementation_constraints": [
                "Fast first-contentful-paint (<1.2s)",
                "Component boundary isolation and modular prop typing",
                "Full keyboard and screen reader accessibility compliance",
                "Zero third-party runtime stylesheet injection",
            ],
        }

        if self._simulate_missing_fields:
            del blueprint_kwargs["design_tokens"]

        blueprint = WebsiteDesignBlueprint(**blueprint_kwargs)

        provider_meta = {
            "provider": self.provider_name,
            "model": self.model_name,
            "components_count": len(component_taxonomy),
            "pages_count": len(pages),
            "breakpoints_count": len(responsive_breakpoints),
        }

        return blueprint, provider_meta


# ── Provider Factory ──────────────────────────────────────────────────────────

def get_design_blueprint_provider(
    provider_override: Optional[AIDesignBlueprintProvider] = None,
) -> AIDesignBlueprintProvider:
    """Returns the active AI Design Blueprint Provider based on configuration."""
    if provider_override:
        return provider_override

    provider_type = getattr(settings, "AI_PROVIDER", "mock").lower()

    if provider_type == "mock":
        return MockDesignBlueprintProvider()

    if provider_type in ("nemotron", "nvidia"):
        if not getattr(settings, "NEMOTRON_ENABLED", False) or not getattr(settings, "NEMOTRON_API_KEY", ""):
            raise AIProviderConfigurationError(
                "NEMOTRON provider was specified but NEMOTRON_ENABLED is False or NEMOTRON_API_KEY is missing."
            )
        return MockDesignBlueprintProvider(
            custom_provider_name="nemotron_design_adapter",
            custom_model_name=getattr(settings, "NEMOTRON_MODEL", "nvidia/llama-3.1-nemotron-ultra-253b-v1"),
        )

    raise AIProviderConfigurationError(f"Unsupported AI_PROVIDER configured: '{provider_type}'")
