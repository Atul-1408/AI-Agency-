"""
Phase 6 Stage 6.3 — Design System + Site Architecture Blueprint Schemas.

Enforces:
1. Complete, structured implementation-ready blueprint (design tokens, component taxonomy,
   page architecture, responsive system, asset requirements, accessibility, interactions).
2. Strict architectural boundaries: ZERO executable code, ZERO HTML/CSS/JSX/TSX.
3. Integrity validations: valid component references, route preservation, unique IDs,
   safe URLs, and prompt injection neutralization.
4. Response models for design blueprints.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Literal, Optional
import uuid

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.website_specification import assert_safe_text, assert_safe_url_path


# ── Design Tokens ─────────────────────────────────────────────────────────────

class ColorTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = Field(..., min_length=1, max_length=50)
    secondary: str = Field(..., min_length=1, max_length=50)
    accent: str = Field(..., min_length=1, max_length=50)
    background: str = Field(..., min_length=1, max_length=50)
    surface: str = Field(..., min_length=1, max_length=50)
    surface_elevated: str = Field(..., min_length=1, max_length=50)
    text: str = Field(..., min_length=1, max_length=50)
    text_muted: str = Field(..., min_length=1, max_length=50)
    border: str = Field(..., min_length=1, max_length=50)
    success: str = Field(default="#39C98A", max_length=50)
    warning: str = Field(default="#E8B968", max_length=50)
    error: str = Field(default="#F87171", max_length=50)

    @field_validator("*")
    @classmethod
    def validate_color_token(cls, v: str) -> str:
        clean = assert_safe_text(v, "color_token")
        if not re.match(r"^(#[0-9a-fA-F]{3,8}|rgba?\([0-9\s,\.%]+\)|hsla?\([0-9\s,\.%]+\)|[a-zA-Z\-]+)$", clean):
            raise ValueError(f"Invalid color value: '{clean}'")
        return clean


class TypographyTokens(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading_font: str = Field(..., min_length=1, max_length=100)
    body_font: str = Field(..., min_length=1, max_length=100)
    mono_font: str = Field(default="ui-monospace, monospace", max_length=100)
    heading_weights: List[str] = Field(default_factory=lambda: ["600", "700", "800"])
    body_weights: List[str] = Field(default_factory=lambda: ["400", "500"])
    scale: Dict[str, str] = Field(
        default_factory=lambda: {
            "xs": "0.75rem",
            "sm": "0.875rem",
            "base": "1rem",
            "lg": "1.125rem",
            "xl": "1.25rem",
            "2xl": "1.5rem",
            "3xl": "2rem",
            "4xl": "2.5rem",
        }
    )

    @field_validator("heading_font", "body_font", "mono_font")
    @classmethod
    def validate_font_names(cls, v: str) -> str:
        return assert_safe_text(v, "font_name")


class DesignTokens(BaseModel):
    """Complete design tokens specification. Raw tokens only — NO CSS output."""
    model_config = ConfigDict(extra="forbid")

    colors: ColorTokens
    typography: TypographyTokens
    spacing: Dict[str, str] = Field(
        default_factory=lambda: {
            "xs": "0.25rem",
            "sm": "0.5rem",
            "md": "1rem",
            "lg": "1.5rem",
            "xl": "2rem",
            "2xl": "3rem",
            "3xl": "4rem",
        }
    )
    radius: Dict[str, str] = Field(
        default_factory=lambda: {
            "sm": "0.25rem",
            "md": "0.5rem",
            "lg": "0.75rem",
            "xl": "1rem",
            "full": "9999px",
        }
    )
    shadows: Dict[str, str] = Field(
        default_factory=lambda: {
            "sm": "0 1px 2px rgba(0,0,0,0.05)",
            "md": "0 4px 6px rgba(0,0,0,0.1)",
            "lg": "0 10px 15px rgba(0,0,0,0.1)",
        }
    )
    container: Dict[str, str] = Field(
        default_factory=lambda: {
            "max_width": "1280px",
            "gutters": "1.5rem",
        }
    )


# ── Responsive Breakpoint System ──────────────────────────────────────────────

class ResponsiveBreakpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=50)
    min_width: str = Field(..., min_length=1, max_length=50)
    layout_behavior: str = Field(..., min_length=1, max_length=255)
    typography_behavior: str = Field(..., min_length=1, max_length=255)
    spacing_behavior: str = Field(..., min_length=1, max_length=255)
    navigation_behavior: str = Field(..., min_length=1, max_length=255)
    component_behavior: str = Field(..., min_length=1, max_length=255)

    @field_validator("*")
    @classmethod
    def validate_breakpoint_fields(cls, v: str) -> str:
        return assert_safe_text(v, "breakpoint_field")


# ── Component Taxonomy & Catalog ──────────────────────────────────────────────

COMPONENT_CATEGORIES = Literal[
    "LAYOUT",
    "NAVIGATION",
    "TYPOGRAPHY",
    "CONTENT",
    "MEDIA",
    "FORMS",
    "CTA",
    "FEEDBACK",
    "DATA",
    "FOOTER",
]


class ComponentSpecification(BaseModel):
    """Component design catalog specification. NO component source code."""
    model_config = ConfigDict(extra="forbid")

    component_id: str = Field(..., min_length=1, max_length=100)
    component_name: str = Field(..., min_length=1, max_length=150)
    category: COMPONENT_CATEGORIES
    purpose: str = Field(..., min_length=1, max_length=500)
    variants: List[str] = Field(default_factory=lambda: ["default"])
    required_props: List[str] = Field(default_factory=list)
    optional_props: List[str] = Field(default_factory=list)
    accessibility_requirements: List[str] = Field(default_factory=list)
    responsive_behavior: str = Field(default="fluid-full-width", max_length=255)
    allowed_usage: str = Field(default="global", max_length=255)
    dependencies: List[str] = Field(default_factory=list)

    @field_validator("component_id")
    @classmethod
    def validate_comp_id(cls, v: str) -> str:
        clean = assert_safe_text(v, "component_id")
        if not re.match(r"^[a-zA-Z0-9_\-]+$", clean):
            raise ValueError(f"component_id must be alphanumeric with underscores/dashes: '{clean}'")
        return clean

    @field_validator("component_name", "purpose", "responsive_behavior", "allowed_usage")
    @classmethod
    def validate_comp_texts(cls, v: str) -> str:
        return assert_safe_text(v, "component_text")

    @field_validator("variants", "required_props", "optional_props", "accessibility_requirements", "dependencies")
    @classmethod
    def validate_lists(cls, items: List[str]) -> List[str]:
        return [assert_safe_text(item, "comp_list_item") for item in items]


# ── Section & Page Architecture ───────────────────────────────────────────────

class SectionBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(..., min_length=1, max_length=100)
    section_type: str = Field(..., min_length=1, max_length=100)
    purpose: str = Field(..., min_length=1, max_length=500)
    component_refs: List[str] = Field(..., min_length=1)
    content_refs: List[str] = Field(default_factory=list)
    layout: str = Field(default="single-column", max_length=100)
    alignment: str = Field(default="center", max_length=100)
    spacing: str = Field(default="md", max_length=100)
    responsive_behavior: str = Field(default="stack-on-mobile", max_length=255)
    visual_priority: Literal["high", "medium", "low"] = "medium"
    accessibility: str = Field(default="Semantic section with accessible heading", max_length=255)
    interaction: str = Field(default="none", max_length=255)

    @field_validator("*")
    @classmethod
    def validate_section_strings(cls, v: Any) -> Any:
        if isinstance(v, str):
            return assert_safe_text(v, "section_blueprint_field")
        if isinstance(v, list):
            return [assert_safe_text(item, "ref_item") for item in v]
        return v


class PageBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page_id: str = Field(..., min_length=1, max_length=100)
    route: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=150)
    purpose: str = Field(..., min_length=1, max_length=500)
    layout_type: str = Field(default="standard-page", max_length=100)
    section_order: List[str] = Field(..., min_length=1)
    sections: List[SectionBlueprint] = Field(..., min_length=1)
    component_refs: List[str] = Field(default_factory=list)
    navigation_refs: List[str] = Field(default_factory=list)
    seo: Dict[str, str] = Field(default_factory=dict)
    responsive_rules: List[str] = Field(default_factory=list)
    accessibility_rules: List[str] = Field(default_factory=list)

    @field_validator("route")
    @classmethod
    def validate_route(cls, v: str) -> str:
        return assert_safe_url_path(v, "page_blueprint.route")

    @field_validator("page_id")
    @classmethod
    def validate_page_id(cls, v: str) -> str:
        clean = assert_safe_text(v, "page_id")
        if not re.match(r"^[a-zA-Z0-9_\-]+$", clean):
            raise ValueError(f"page_id must be alphanumeric with underscores/dashes: '{clean}'")
        return clean

    @field_validator("name", "purpose", "layout_type")
    @classmethod
    def validate_page_texts(cls, v: str) -> str:
        return assert_safe_text(v, "page_text")


# ── Site Architecture ─────────────────────────────────────────────────────────

class SiteArchitecture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = Field(default="/")
    pages: List[str] = Field(..., min_length=1)
    navigation: List[Dict[str, Any]] = Field(default_factory=list)
    footer: Dict[str, Any] = Field(default_factory=dict)
    global_components: List[str] = Field(default_factory=list)
    page_dependencies: Dict[str, List[str]] = Field(default_factory=dict)


# ── Asset Requirements ────────────────────────────────────────────────────────

ASSET_TYPES = Literal["IMAGE", "VIDEO", "ICON", "LOGO", "ILLUSTRATION", "FONT"]


class AssetRequirement(BaseModel):
    """Specification of required media assets. NO file downloading or generating."""
    model_config = ConfigDict(extra="forbid")

    asset_id: str = Field(..., min_length=1, max_length=100)
    type: ASSET_TYPES
    purpose: str = Field(..., min_length=1, max_length=500)
    page: str = Field(..., min_length=1, max_length=100)
    section: str = Field(..., min_length=1, max_length=100)
    required: bool = True
    source: str = Field(default="CLIENT_ASSET", max_length=100)
    dimensions: Optional[str] = Field(default=None, max_length=50)
    aspect_ratio: Optional[str] = Field(default=None, max_length=50)
    accessibility_alt_requirement: str = Field(..., min_length=1, max_length=300)
    placeholder_allowed: bool = True

    @field_validator("*")
    @classmethod
    def validate_asset_fields(cls, v: Any) -> Any:
        if isinstance(v, str):
            return assert_safe_text(v, "asset_field")
        return v


# ── Interaction & Motion ──────────────────────────────────────────────────────

INTERACTION_TRIGGERS = Literal[
    "hover",
    "focus",
    "active",
    "expanded",
    "collapsed",
    "modal",
    "accordion",
    "carousel",
    "scroll_reveal",
    "transition",
]


class InteractionSpecification(BaseModel):
    """Specification of micro-interactions. NO JavaScript/CSS code."""
    model_config = ConfigDict(extra="forbid")

    interaction_id: str = Field(..., min_length=1, max_length=100)
    trigger: INTERACTION_TRIGGERS
    behavior: str = Field(..., min_length=1, max_length=300)
    duration: str = Field(default="200ms", max_length=50)
    reduced_motion_behavior: str = Field(default="instant", max_length=150)
    accessibility_behavior: str = Field(default="Focus ring visible on keyboard interaction", max_length=300)

    @field_validator("*")
    @classmethod
    def validate_interaction_fields(cls, v: str) -> str:
        return assert_safe_text(v, "interaction_field")


# ── Accessibility Blueprint ───────────────────────────────────────────────────

class AccessibilityBlueprint(BaseModel):
    """Comprehensive WCAG and assistive technology blueprint."""
    model_config = ConfigDict(extra="forbid")

    keyboard_navigation: str = Field(..., min_length=1, max_length=500)
    focus_behavior: str = Field(..., min_length=1, max_length=500)
    semantic_structure: str = Field(..., min_length=1, max_length=500)
    heading_hierarchy: str = Field(..., min_length=1, max_length=500)
    form_labels: str = Field(..., min_length=1, max_length=500)
    alt_text_requirements: str = Field(..., min_length=1, max_length=500)
    color_contrast_requirement: str = Field(default="WCAG 2.1 AA 4.5:1 minimum contrast", max_length=500)
    reduced_motion_behavior: str = Field(default="Honor prefers-reduced-motion media query", max_length=500)
    screen_reader_considerations: str = Field(..., min_length=1, max_length=500)

    @field_validator("*")
    @classmethod
    def validate_a11y_fields(cls, v: str) -> str:
        return assert_safe_text(v, "accessibility_field")


# ── Content Mapping ───────────────────────────────────────────────────────────

class BlueprintContentMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: str = Field(..., min_length=1, max_length=100)
    section: str = Field(..., min_length=1, max_length=100)
    content_type: str = Field(..., min_length=1, max_length=100)
    required: bool = True
    status: Literal["CONFIRMED", "GENERATED_DRAFT", "UNKNOWN", "NEEDS_CLIENT_INPUT"] = "CONFIRMED"
    source: str = Field(default="PRD", max_length=100)
    notes: str = Field(default="", max_length=500)

    @field_validator("*")
    @classmethod
    def validate_content_mapping_fields(cls, v: Any) -> Any:
        if isinstance(v, str):
            return assert_safe_text(v, "content_mapping_field")
        return v


# ── Top-Level Website Design Blueprint ────────────────────────────────────────

class WebsiteDesignBlueprint(BaseModel):
    """
    Comprehensive implementation-ready design blueprint produced in Phase 6.3.
    Contains strictly structured architectural specifications — ZERO executable source code.
    """
    model_config = ConfigDict(extra="forbid")

    blueprint_version: int = Field(default=1, ge=1)
    source_generation_id: str = Field(..., min_length=1)
    source_generation_version: int = Field(..., ge=1)
    project_name: str = Field(..., min_length=1, max_length=255)
    project_slug: str = Field(..., min_length=1, max_length=255)
    design_tokens: DesignTokens
    responsive_breakpoints: List[ResponsiveBreakpoint] = Field(..., min_length=1)
    component_taxonomy: List[ComponentSpecification] = Field(..., min_length=1)
    pages: List[PageBlueprint] = Field(..., min_length=1)
    site_architecture: SiteArchitecture
    asset_requirements: List[AssetRequirement] = Field(default_factory=list)
    interactions: List[InteractionSpecification] = Field(default_factory=list)
    accessibility: AccessibilityBlueprint
    content_mapping: List[BlueprintContentMapping] = Field(default_factory=list)
    implementation_constraints: List[str] = Field(
        default_factory=lambda: [
            "Fast first-contentful-paint (<1.2s)",
            "Strict component boundary isolation",
            "Zero client-side script errors",
            "Full keyboard accessibility compliance",
        ]
    )

    @field_validator("project_name", "project_slug")
    @classmethod
    def validate_project_meta(cls, v: str) -> str:
        return assert_safe_text(v, "project_meta")

    @field_validator("implementation_constraints")
    @classmethod
    def validate_constraints(cls, items: List[str]) -> List[str]:
        return [assert_safe_text(item, "constraint") for item in items]

    @model_validator(mode="after")
    def validate_integrity(self) -> "WebsiteDesignBlueprint":
        # 1. Unique page_ids
        page_ids = [p.page_id for p in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError(f"Duplicate page_ids found in pages blueprint: {page_ids}")

        # 2. Unique routes
        routes = [p.route for p in self.pages]
        if len(routes) != len(set(routes)):
            raise ValueError(f"Duplicate routes found in pages blueprint: {routes}")

        # 3. Root route exists
        if "/" not in routes:
            raise ValueError("Pages blueprint must include a root page ('/')")

        # 4. Component reference validity
        valid_comp_ids = {c.component_id for c in self.component_taxonomy}
        for page in self.pages:
            for sec in page.sections:
                for comp_ref in sec.component_refs:
                    if comp_ref not in valid_comp_ids:
                        raise ValueError(
                            f"Section '{sec.section_id}' references unknown component '{comp_ref}' "
                            f"not found in component_taxonomy."
                        )

        return self


# ── Blueprint API Models ──────────────────────────────────────────────────────

class DesignBlueprintResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    build_session_id: uuid.UUID
    project_id: uuid.UUID
    owner_id: str
    source_generation_id: uuid.UUID
    source_generation_version: int
    blueprint_version: int
    status: str
    specification_artifact_id: Optional[uuid.UUID] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata", "blueprint_metadata"),
    )


class DesignBlueprintDetailResponse(DesignBlueprintResponse):
    blueprint: Optional[WebsiteDesignBlueprint] = None
    project_name: Optional[str] = None
    project_slug: Optional[str] = None


class DesignBlueprintListResponse(BaseModel):
    items: List[DesignBlueprintResponse]
    total: int
    completed_count: int
    failed_count: int
    active_count: int


class DesignBlueprintCancelRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)

