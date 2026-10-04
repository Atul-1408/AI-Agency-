"""
Phase 6 Stage 6.2 — Structured Website Specification and Generation Schemas.

Enforces:
1. Strict JSON-compatible structured website specification (NO executable code, NO JSX/HTML/CSS).
2. Deep validation: safe paths, unique page IDs, unique paths, structured design tokens, explicit content sources.
3. Anti-injection and executable-code rejection.
4. Response models for website generations.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Literal, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import AliasChoices


# ── Executable Code & Injection Sanitizer ──────────────────────────────────────

DANGEROUS_PATTERNS = [
    re.compile(r"<script[\s>]", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"data:text/html", re.IGNORECASE),
    re.compile(r"\beval\(", re.IGNORECASE),
    re.compile(r"\bexec\(", re.IGNORECASE),
    re.compile(r"__proto__", re.IGNORECASE),
    re.compile(r"\bchild_process\b", re.IGNORECASE),
    re.compile(r"\bos\.system\b", re.IGNORECASE),
    re.compile(r"\bsubprocess\b", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"<\s*/?\s*(html|body|iframe|object|embed)\b", re.IGNORECASE),
]


def assert_safe_text(value: str, field_name: str) -> str:
    """Verifies that a text field does not contain executable injection vectors."""
    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(value):
            raise ValueError(
                f"Field '{field_name}' contains disallowed executable pattern: {pattern.pattern}"
            )
    return value


def assert_safe_url_path(path: str, field_name: str = "path") -> str:
    """Validates that a URL path is safe, relative, and properly formed."""
    if not path or not path.startswith("/"):
        raise ValueError(f"'{field_name}' must start with a leading slash ('/'). Got: '{path}'")
    if ".." in path:
        raise ValueError(f"Directory traversal ('..') is disallowed in '{field_name}'.")
    if any(char in path for char in ["<", ">", '"', "'", "`", "\\", " ", ";"]):
        raise ValueError(f"'{field_name}' contains unsafe characters.")
    if path.lower().startswith(("/javascript:", "/data:")):
        raise ValueError(f"Unsafe pseudo-protocol in '{field_name}'.")
    return path


# ── Navigation & Section Specifications ───────────────────────────────────────

class NavigationItemSpecification(BaseModel):
    """Structured navigation element."""
    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., min_length=1, max_length=100)
    path: str = Field(..., min_length=1, max_length=255)
    order: int = Field(default=1, ge=1)
    visibility: Literal["all", "header", "footer", "mobile"] = Field(default="all")

    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        return assert_safe_text(v, "label")

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        return assert_safe_url_path(v, "navigation.path")


class SectionSpecification(BaseModel):
    """Conceptual section breakdown on a page. Contains NO HTML/CSS/JSX."""
    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(..., min_length=1, max_length=100)
    type: str = Field(..., min_length=1, max_length=100)
    purpose: str = Field(..., min_length=1, max_length=500)
    heading: str = Field(..., min_length=1, max_length=255)
    supporting_content: str = Field(default="", max_length=2000)
    layout: str = Field(default="single-column", max_length=100)
    components: List[str] = Field(default_factory=list)
    cta: Optional[str] = Field(default=None, max_length=255)
    visibility: Literal["visible", "conditional", "hidden"] = Field(default="visible")
    responsive_behavior: str = Field(default="stack-on-mobile", max_length=100)

    @field_validator("section_id", "type", "purpose", "heading", "supporting_content", "layout")
    @classmethod
    def validate_texts(cls, v: str) -> str:
        return assert_safe_text(v, "section_field")

    @field_validator("components")
    @classmethod
    def validate_components(cls, components: List[str]) -> List[str]:
        for c in components:
            assert_safe_text(c, "component")
            if "<" in c or ">" in c or "/" in c:
                raise ValueError(
                    f"Component names must be conceptual tokens (e.g. 'HeroBanner'), not markup tags: '{c}'"
                )
        return components


# ── Page Specification ────────────────────────────────────────────────────────

class PageSpecification(BaseModel):
    """Specification of an individual page within the website."""
    model_config = ConfigDict(extra="forbid")

    page_id: str = Field(..., min_length=1, max_length=100)
    path: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=150)
    purpose: str = Field(..., min_length=1, max_length=500)
    priority: Literal["primary", "secondary", "utility"] = Field(default="primary")
    seo_title: str = Field(..., min_length=1, max_length=200)
    seo_description: str = Field(..., min_length=1, max_length=350)
    sections: List[SectionSpecification] = Field(..., min_length=1)
    primary_cta: Optional[str] = Field(default=None, max_length=255)
    secondary_cta: Optional[str] = Field(default=None, max_length=255)

    @field_validator("page_id")
    @classmethod
    def validate_page_id(cls, v: str) -> str:
        clean = assert_safe_text(v, "page_id")
        if not re.match(r"^[a-zA-Z0-9_\-]+$", clean):
            raise ValueError(f"page_id must be alphanumeric with underscores/dashes: '{clean}'")
        return clean

    @field_validator("path")
    @classmethod
    def validate_page_path(cls, v: str) -> str:
        return assert_safe_url_path(v, "page.path")

    @field_validator("name", "purpose", "seo_title", "seo_description")
    @classmethod
    def validate_page_texts(cls, v: str) -> str:
        return assert_safe_text(v, "page_text")


# ── Design System Specification ───────────────────────────────────────────────

class TypographySpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading_family: str = Field(..., min_length=1, max_length=100)
    body_family: str = Field(..., min_length=1, max_length=100)
    heading_scale: Dict[str, str] = Field(
        default_factory=lambda: {"h1": "2.5rem", "h2": "2rem", "h3": "1.5rem", "h4": "1.25rem"}
    )
    body_scale: Dict[str, str] = Field(
        default_factory=lambda: {"sm": "0.875rem", "base": "1rem", "lg": "1.125rem"}
    )

    @field_validator("heading_family", "body_family")
    @classmethod
    def validate_families(cls, v: str) -> str:
        return assert_safe_text(v, "font_family")


class ColorPaletteSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str = Field(..., min_length=1, max_length=50)
    secondary: str = Field(..., min_length=1, max_length=50)
    accent: str = Field(..., min_length=1, max_length=50)
    background: str = Field(..., min_length=1, max_length=50)
    surface: str = Field(..., min_length=1, max_length=50)
    text: str = Field(..., min_length=1, max_length=50)
    muted: str = Field(..., min_length=1, max_length=50)

    @field_validator("primary", "secondary", "accent", "background", "surface", "text", "muted")
    @classmethod
    def validate_color(cls, v: str) -> str:
        clean = assert_safe_text(v, "color")
        # Ensure it is a valid hex, rgb, hsl, or css color token without executable tricks
        if not re.match(r"^(#[0-9a-fA-F]{3,8}|rgba?\([0-9\s,\.%]+\)|hsla?\([0-9\s,\.%]+\)|[a-zA-Z\-]+)$", clean):
            raise ValueError(f"Invalid color value: '{clean}'")
        return clean


class DesignSystemSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visual_direction: str = Field(..., min_length=1, max_length=500)
    typography: TypographySpecification
    color_palette: ColorPaletteSpecification
    spacing: Dict[str, str] = Field(
        default_factory=lambda: {"xs": "0.25rem", "sm": "0.5rem", "md": "1rem", "lg": "2rem", "xl": "3rem"}
    )
    border_radius: Dict[str, str] = Field(
        default_factory=lambda: {"sm": "0.25rem", "md": "0.5rem", "lg": "1rem", "full": "9999px"}
    )
    shadows: Dict[str, str] = Field(
        default_factory=lambda: {"sm": "0 1px 2px rgba(0,0,0,0.05)", "md": "0 4px 6px rgba(0,0,0,0.1)", "lg": "0 10px 15px rgba(0,0,0,0.1)"}
    )
    imagery_direction: str = Field(default="Clean modern professional imagery", max_length=500)
    icon_direction: str = Field(default="Consistent modern line icons", max_length=500)
    motion_direction: str = Field(default="Subtle smooth micro-interactions", max_length=500)
    responsive_strategy: str = Field(default="Mobile-first fluid responsive grid", max_length=500)

    @field_validator("visual_direction", "imagery_direction", "icon_direction", "motion_direction", "responsive_strategy")
    @classmethod
    def validate_design_texts(cls, v: str) -> str:
        return assert_safe_text(v, "design_text")


# ── Content Strategy Specification ───────────────────────────────────────────

CONTENT_SOURCE_TYPES = Literal[
    "PRD",
    "CLIENT_REQUIREMENT",
    "CLIENT_APPROVED_CONTENT",
    "BUSINESS_INFORMATION",
    "GENERATED_DRAFT",
]


class ContentSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: str = Field(..., min_length=1, max_length=100)
    section: str = Field(..., min_length=1, max_length=100)
    content_type: str = Field(..., min_length=1, max_length=100)
    required: bool = True
    source: CONTENT_SOURCE_TYPES = "PRD"
    notes: str = Field(default="", max_length=1000)

    @field_validator("page", "section", "content_type", "notes")
    @classmethod
    def validate_content_texts(cls, v: str) -> str:
        return assert_safe_text(v, "content_text")


# ── Top-Level Website Specification ───────────────────────────────────────────

class WebsiteSpecification(BaseModel):
    """
    Structured, fully validated website specification produced by Phase 6.2.
    Contains strictly planning/specification data — ZERO executable source code.
    """
    model_config = ConfigDict(extra="forbid")

    specification_version: str = Field(default="1.0.0")
    generation_version: int = Field(default=1, ge=1)
    project_name: str = Field(..., min_length=1, max_length=255)
    project_slug: str = Field(..., min_length=1, max_length=255)
    website_goal: str = Field(..., min_length=1, max_length=1000)
    target_audience: str = Field(..., min_length=1, max_length=1000)
    primary_cta: str = Field(..., min_length=1, max_length=255)
    secondary_ctas: List[str] = Field(default_factory=list)
    navigation: List[NavigationItemSpecification] = Field(..., min_length=1)
    pages: List[PageSpecification] = Field(..., min_length=1)
    design_system: DesignSystemSpecification
    content_strategy: List[ContentSpecification] = Field(default_factory=list)
    accessibility_requirements: List[str] = Field(
        default_factory=lambda: ["WCAG 2.1 AA Compliance", "Semantic HTML landmarks", "Sufficient color contrast"]
    )
    responsive_requirements: List[str] = Field(
        default_factory=lambda: ["Mobile (<640px)", "Tablet (640px-1024px)", "Desktop (>1024px)"]
    )
    technical_constraints: List[str] = Field(
        default_factory=lambda: ["Fast initial page load (<1.5s)", "Zero JavaScript errors", "Clean separation of presentation"]
    )
    open_questions: List[str] = Field(default_factory=list)
    source_prd_id: str = Field(..., min_length=1)
    source_prd_version: int = Field(..., ge=1)

    @field_validator(
        "project_name",
        "project_slug",
        "website_goal",
        "target_audience",
        "primary_cta",
    )
    @classmethod
    def validate_general_texts(cls, v: str) -> str:
        return assert_safe_text(v, "general_text")

    @field_validator("secondary_ctas", "accessibility_requirements", "responsive_requirements", "technical_constraints", "open_questions")
    @classmethod
    def validate_text_lists(cls, items: List[str]) -> List[str]:
        return [assert_safe_text(item, "list_item") for item in items]

    @model_validator(mode="after")
    def validate_integrity(self) -> "WebsiteSpecification":
        # 1. Unique page_ids
        page_ids = [p.page_id for p in self.pages]
        if len(page_ids) != len(set(page_ids)):
            raise ValueError(f"Duplicate page_ids found in pages specification: {page_ids}")

        # 2. Unique paths
        paths = [p.path for p in self.pages]
        if len(paths) != len(set(paths)):
            raise ValueError(f"Duplicate paths found in pages specification: {paths}")

        # 3. Root path exists
        if "/" not in paths:
            raise ValueError("Pages specification must include a root page ('/')")

        # 4. Navigation paths should point to valid page paths
        for nav in self.navigation:
            if nav.path not in paths:
                raise ValueError(
                    f"Navigation path '{nav.path}' does not correspond to any defined page path."
                )

        return self


# ── Generation API Models ─────────────────────────────────────────────────────

class WebsiteGenerationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    build_session_id: uuid.UUID
    project_id: uuid.UUID
    owner_id: str
    source_prd_id: uuid.UUID
    source_prd_version: int
    generation_version: int
    status: str
    provider: str
    model: str
    specification_artifact_id: Optional[uuid.UUID] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("metadata", "generation_metadata"),
    )


class WebsiteGenerationDetailResponse(WebsiteGenerationResponse):
    specification: Optional[WebsiteSpecification] = None
    project_name: Optional[str] = None
    project_slug: Optional[str] = None


class WebsiteGenerationListResponse(BaseModel):
    items: List[WebsiteGenerationResponse]
    total: int
    completed_count: int
    failed_count: int
    active_count: int
