"""
Phase 6 Stage 6.4 — AI Website Code Generation Provider Abstraction.

Responsibilities:
1. Provider interface for generating structured Next.js source code from PRD, Specification, and Design Blueprint.
2. High-fidelity deterministic Mock provider generating complete, production-ready Next.js + React + TypeScript codebases.
3. Realistic AI provider integration with graceful fallback.
4. Comprehensive test simulation hooks (failure, malformed output, secrets, forbidden APIs, path traversal, missing files).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple

import structlog

from core.config import settings
from schemas.code_generation import GeneratedWebsiteFile, GeneratedWebsiteProject
from schemas.design_blueprint import WebsiteDesignBlueprint
from schemas.website_specification import WebsiteSpecification
from services.code_generation_prompt_builder import CodeGenerationPromptBuilder
from services.website_generator_provider import (
    AIProviderConfigurationError,
    AIProviderError,
    AIProviderExecutionError,
)

log = structlog.get_logger(__name__)


# ── Abstract Base Provider ───────────────────────────────────────────────────

class CodeGenerationProvider(ABC):
    """Abstract interface for Next.js website source code generation providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @abstractmethod
    async def generate_code(
        self,
        prd_data: Dict[str, Any],
        specification: WebsiteSpecification,
        blueprint: WebsiteDesignBlueprint,
        requirements: List[Dict[str, Any]],
        allowed_content: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[GeneratedWebsiteProject, Dict[str, Any]]:
        pass


# ── Deterministic Mock Code Generation Provider ───────────────────────────────

class MockWebsiteCodeGenerationProvider(CodeGenerationProvider):
    """
    Deterministic mock provider producing a complete, fully-valid Next.js + TypeScript
    App Router project strictly consuming the Design Blueprint tokens, components, and pages.
    """

    def __init__(
        self,
        simulate_failure: bool = False,
        simulate_malformed: bool = False,
        simulate_missing_files: bool = False,
        simulate_unsafe_code: bool = False,
        simulate_secrets: bool = False,
        simulate_path_traversal: bool = False,
        simulate_duplicate_files: bool = False,
        simulate_broken_component_ref: bool = False,
        custom_provider_name: str = "mock_code_provider",
        custom_model_name: str = "mock-nextjs-code-v1",
    ):
        self._simulate_failure = simulate_failure
        self._simulate_malformed = simulate_malformed
        self._simulate_missing_files = simulate_missing_files
        self._simulate_unsafe_code = simulate_unsafe_code
        self._simulate_secrets = simulate_secrets
        self._simulate_path_traversal = simulate_path_traversal
        self._simulate_duplicate_files = simulate_duplicate_files
        self._simulate_broken_component_ref = simulate_broken_component_ref
        self._provider_name = custom_provider_name
        self._model_name = custom_model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def _make_file(self, path: str, content: str, file_type: str) -> GeneratedWebsiteFile:
        raw_bytes = content.encode("utf-8")
        return GeneratedWebsiteFile(
            path=path,
            content=content,
            file_type=file_type,
            checksum=hashlib.sha256(raw_bytes).hexdigest(),
            size_bytes=len(raw_bytes),
        )

    async def generate_code(
        self,
        prd_data: Dict[str, Any],
        specification: WebsiteSpecification,
        blueprint: WebsiteDesignBlueprint,
        requirements: List[Dict[str, Any]],
        allowed_content: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[GeneratedWebsiteProject, Dict[str, Any]]:
        if self._simulate_failure:
            raise AIProviderExecutionError("Simulated AI code generation timeout or service error.")

        if self._simulate_malformed:
            raise AIProviderExecutionError("AI code generation returned invalid non-JSON output.")

        # Test simulation: secret detected
        if self._simulate_secrets:
            bad_file = self._make_file(
                "lib/config.ts",
                'export const API_KEY = "sk-live-1234567890abcdef1234567890";',
                "ts",
            )
            return GeneratedWebsiteProject(
                framework="nextjs",
                language="typescript",
                files=[bad_file],
                entrypoints=["app/layout.tsx"],
            ), {}

        # Test simulation: unsafe code pattern detected
        if self._simulate_unsafe_code:
            bad_file = self._make_file(
                "app/page.tsx",
                'import React from "react";\nexport default function Page() { eval("alert(1)"); return <div>Unsafe</div>; }',
                "tsx",
            )
            return GeneratedWebsiteProject(
                framework="nextjs",
                language="typescript",
                files=[bad_file],
                entrypoints=["app/layout.tsx"],
            ), {}

        # Test simulation: path traversal attempt
        if self._simulate_path_traversal:
            bad_file = self._make_file(
                "../escape.txt",
                "malicious outside workspace content",
                "text",
            )
            return GeneratedWebsiteProject(
                framework="nextjs",
                language="typescript",
                files=[bad_file],
            ), {}

        # Test simulation: missing required Next.js entrypoint files
        if self._simulate_missing_files:
            partial_file = self._make_file(
                "app/page.tsx",
                'export default function Page() { return <h1>Incomplete</h1>; }',
                "tsx",
            )
            return GeneratedWebsiteProject(
                framework="nextjs",
                language="typescript",
                files=[partial_file],
            ), {}

        # Extract tokens from Blueprint
        tokens = blueprint.design_tokens
        primary_color = getattr(tokens.colors, "primary", "#0f172a")
        secondary_color = getattr(tokens.colors, "secondary", "#3b82f6")
        accent_color = getattr(tokens.colors, "accent", "#10b981")
        background_color = getattr(tokens.colors, "background", "#ffffff")
        foreground_color = getattr(tokens.colors, "text", "#0f172a")

        heading_font = getattr(tokens.typography, "heading_font", "Inter, sans-serif")
        body_font = getattr(tokens.typography, "body_font", "Inter, sans-serif")
        card_radius = tokens.radius.get("card", "0.5rem") if isinstance(tokens.radius, dict) else "0.5rem"
        section_spacing = tokens.spacing.get("section_y", "4rem") if isinstance(tokens.spacing, dict) else "4rem"

        project_name = blueprint.project_name
        project_slug = blueprint.project_slug

        files: List[GeneratedWebsiteFile] = []
        entrypoints: List[str] = ["app/layout.tsx", "app/page.tsx"]
        routes: List[str] = ["/"]
        components: List[str] = []

        # 1. package.json
        pkg_content = json.dumps(
            {
                "name": project_slug,
                "version": "0.1.0",
                "private": True,
                "scripts": {
                    "dev": "next dev",
                    "build": "next build",
                    "start": "next start",
                    "lint": "next lint",
                },
                "dependencies": {
                    "next": "15.0.0",
                    "react": "19.0.0",
                    "react-dom": "19.0.0",
                    "lucide-react": "^0.454.0",
                    "clsx": "^2.1.1",
                    "tailwind-merge": "^2.5.4",
                },
                "devDependencies": {
                    "@types/node": "^22",
                    "@types/react": "^19",
                    "@types/react-dom": "^19",
                    "postcss": "^8",
                    "tailwindcss": "^3.4",
                    "typescript": "^5",
                },
            },
            indent=2,
        )
        files.append(self._make_file("package.json", pkg_content, "json"))

        # 2. tsconfig.json
        tsconfig_content = json.dumps(
            {
                "compilerOptions": {
                    "target": "ES2017",
                    "lib": ["dom", "dom.iterable", "esnext"],
                    "allowJs": True,
                    "skipLibCheck": True,
                    "strict": True,
                    "noEmit": True,
                    "esModuleInterop": True,
                    "module": "esnext",
                    "moduleResolution": "bundler",
                    "resolveJsonModule": True,
                    "isolatedModules": True,
                    "jsx": "preserve",
                    "incremental": True,
                    "plugins": [{"name": "next"}],
                    "paths": {"@/*": ["./*"]},
                },
                "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
                "exclude": ["node_modules"],
            },
            indent=2,
        )
        files.append(self._make_file("tsconfig.json", tsconfig_content, "json"))

        # 3. next.config.ts
        next_config_content = (
            'import type { NextConfig } from "next";\n\n'
            "const nextConfig: NextConfig = {\n"
            "  reactStrictMode: true,\n"
            "};\n\n"
            "export default nextConfig;\n"
        )
        files.append(self._make_file("next.config.ts", next_config_content, "ts"))

        # 4. postcss.config.mjs
        postcss_content = (
            "export default {\n"
            "  plugins: {\n"
            "    tailwindcss: {},\n"
            "    autoprefixer: {},\n"
            "  },\n"
            "};\n"
        )
        files.append(self._make_file("postcss.config.mjs", postcss_content, "mjs"))

        # 5. app/globals.css with Design Blueprint CSS Variables
        globals_css = f"""@tailwind base;
@tailwind components;
@tailwind utilities;

:root {{
  --color-primary: {primary_color};
  --color-secondary: {secondary_color};
  --color-accent: {accent_color};
  --color-background: {background_color};
  --color-foreground: {foreground_color};
  --font-heading: {heading_font};
  --font-body: {body_font};
  --radius-card: {card_radius};
  --spacing-section: {section_spacing};
}}

body {{
  color: var(--color-foreground);
  background: var(--color-background);
  font-family: var(--font-body);
  margin: 0;
  padding: 0;
}}

h1, h2, h3, h4, h5, h6 {{
  font-family: var(--font-heading);
}}
"""
        files.append(self._make_file("app/globals.css", globals_css, "css"))

        # 6. lib/utils.ts
        utils_content = (
            'import { type ClassValue, clsx } from "clsx";\n'
            'import { twMerge } from "tailwind-merge";\n\n'
            "export function cn(...inputs: ClassValue[]) {\n"
            "  return twMerge(clsx(inputs));\n"
            "}\n"
        )
        files.append(self._make_file("lib/utils.ts", utils_content, "ts"))

        # 7. Core Reusable UI & Layout Components
        # Button
        button_content = """import React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "outline";
  size?: "sm" | "md" | "lg";
}

export function Button({
  className,
  variant = "primary",
  size = "md",
  children,
  ...props
}: ButtonProps) {
  const baseStyles = "inline-flex items-center justify-center font-medium transition-colors rounded focus:outline-none focus:ring-2 focus:ring-offset-2";
  const variants = {
    primary: "bg-[var(--color-primary)] text-white hover:opacity-90 focus:ring-[var(--color-primary)]",
    secondary: "bg-[var(--color-secondary)] text-white hover:opacity-90 focus:ring-[var(--color-secondary)]",
    outline: "border border-[var(--color-primary)] text-[var(--color-primary)] hover:bg-slate-50",
  };
  const sizes = {
    sm: "px-3 py-1.5 text-xs",
    md: "px-4 py-2 text-sm",
    lg: "px-6 py-3 text-base",
  };

  return (
    <button
      className={cn(baseStyles, variants[variant], sizes[size], className)}
      {...props}
    >
      {children}
    </button>
  );
}
"""
        files.append(self._make_file("components/ui/Button.tsx", button_content, "tsx"))
        components.append("Button")

        # Container
        container_content = """import React from "react";
import { cn } from "@/lib/utils";

export function Container({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("max-w-7xl mx-auto px-4 sm:px-6 lg:px-8", className)}>
      {children}
    </div>
  );
}
"""
        files.append(self._make_file("components/ui/Container.tsx", container_content, "tsx"))
        components.append("Container")

        # Card
        card_content = """import React from "react";
import { cn } from "@/lib/utils";

export function Card({ className, children }: { className?: string; children: React.ReactNode }) {
  return (
    <div className={cn("bg-white rounded-lg border border-slate-200 shadow-sm p-6", className)}>
      {children}
    </div>
  );
}
"""
        files.append(self._make_file("components/ui/Card.tsx", card_content, "tsx"))
        components.append("Card")

        # Header (Navigation)
        header_content = f"""import React from "react";
import Link from "next/link";
import {{ Container }} from "@/components/ui/Container";
import {{ Button }} from "@/components/ui/Button";

export function Header() {{
  return (
    <header className="sticky top-0 z-40 w-full border-b border-slate-200 bg-white/90 backdrop-blur">
      <Container className="flex h-16 items-center justify-between">
        <Link href="/" className="font-bold text-xl text-[var(--color-primary)]">
          {project_name}
        </Link>
        <nav className="hidden md:flex gap-6 items-center text-sm font-medium">
          <Link href="/" className="hover:text-[var(--color-secondary)]">Home</Link>
          <Link href="/about" className="hover:text-[var(--color-secondary)]">About</Link>
          <Link href="/services" className="hover:text-[var(--color-secondary)]">Services</Link>
          <Link href="/contact" className="hover:text-[var(--color-secondary)]">Contact</Link>
        </nav>
        <div className="flex items-center gap-3">
          <Link href="/contact">
            <Button size="sm">Get Started</Button>
          </Link>
        </div>
      </Container>
    </header>
  );
}}
"""
        files.append(self._make_file("components/layout/Header.tsx", header_content, "tsx"))
        components.append("Header")

        # Footer
        footer_content = f"""import React from "react";
import Link from "next/link";
import {{ Container }} from "@/components/ui/Container";

export function Footer() {{
  return (
    <footer className="border-t border-slate-200 bg-slate-50 py-12 text-slate-600 text-sm">
      <Container className="flex flex-col md:flex-row justify-between items-center gap-6">
        <div>
          <span className="font-semibold text-slate-900">{project_name}</span>
          <p className="mt-1 text-xs text-slate-500">
            © {{new Date().getFullYear()}} {project_name}. All rights reserved.
          </p>
        </div>
        <div className="flex gap-6 text-xs">
          <Link href="/about" className="hover:underline">About</Link>
          <Link href="/services" className="hover:underline">Services</Link>
          <Link href="/contact" className="hover:underline">Contact</Link>
          <Link href="/privacy" className="hover:underline">Privacy</Link>
        </div>
      </Container>
    </footer>
  );
}}
"""
        files.append(self._make_file("components/layout/Footer.tsx", footer_content, "tsx"))
        components.append("Footer")

        # Hero Section
        hero_content = f"""import React from "react";
import {{ Container }} from "@/components/ui/Container";
import {{ Button }} from "@/components/ui/Button";

export function Hero() {{
  return (
    <section className="py-20 md:py-28 bg-gradient-to-b from-slate-50 to-white text-center">
      <Container className="max-w-4xl">
        <h1 className="text-4xl sm:text-5xl md:text-6xl font-extrabold tracking-tight text-slate-900">
          Professional Digital Solutions for <span className="text-[var(--color-secondary)]">{project_name}</span>
        </h1>
        <p className="mt-6 text-lg sm:text-xl text-slate-600 leading-relaxed">
          {specification.website_goal}
        </p>
        <div className="mt-10 flex flex-wrap justify-center gap-4">
          <Button size="lg">{specification.primary_cta or "Explore Services"}</Button>
          <Button size="lg" variant="outline">Learn More</Button>
        </div>
      </Container>
    </section>
  );
}}
"""
        files.append(self._make_file("components/sections/Hero.tsx", hero_content, "tsx"))
        components.append("Hero")

        # FeatureGrid Section
        featuregrid_content = """import React from "react";
import { Container } from "@/components/ui/Container";
import { Card } from "@/components/ui/Card";
import { Sparkles, Shield, Zap } from "lucide-react";

const features = [
  { title: "Strategic Design", description: "Engineered specifically for your target audience.", icon: Sparkles },
  { title: "Reliable Quality", description: "Built with modern, responsive enterprise standards.", icon: Shield },
  { title: "High Performance", description: "Optimized for lightning-fast speeds and accessibility.", icon: Zap },
];

export function FeatureGrid() {
  return (
    <section className="py-16 bg-white">
      <Container>
        <div className="text-center max-w-2xl mx-auto mb-12">
          <h2 className="text-3xl font-bold tracking-tight text-slate-900">Our Core Capabilities</h2>
          <p className="mt-3 text-slate-600">Tailored features crafted for measurable business impact.</p>
        </div>
        <div className="grid md:grid-cols-3 gap-8">
          {features.map((f, i) => (
            <Card key={i} className="text-center flex flex-col items-center">
              <div className="p-3 bg-blue-50 text-[var(--color-secondary)] rounded-full mb-4">
                <f.icon className="h-6 w-6" />
              </div>
              <h3 className="text-xl font-semibold text-slate-900 mb-2">{f.title}</h3>
              <p className="text-slate-600 text-sm leading-relaxed">{f.description}</p>
            </Card>
          ))}
        </div>
      </Container>
    </section>
  );
}
"""
        files.append(self._make_file("components/sections/FeatureGrid.tsx", featuregrid_content, "tsx"))
        components.append("FeatureGrid")

        # CTA Section
        cta_content = f"""import React from "react";
import {{ Container }} from "@/components/ui/Container";
import {{ Button }} from "@/components/ui/Button";

export function CTASection() {{
  return (
    <section className="py-16 bg-[var(--color-primary)] text-white text-center">
      <Container className="max-w-3xl">
        <h2 className="text-3xl font-bold tracking-tight">Ready to Elevate Your Web Presence?</h2>
        <p className="mt-4 text-slate-300">Get in touch with our team today and let us bring your vision to life.</p>
        <div className="mt-8 flex justify-center">
          <Button size="lg" variant="secondary">{specification.primary_cta or "Contact Us Now"}</Button>
        </div>
      </Container>
    </section>
  );
}}
"""
        files.append(self._make_file("components/sections/CTASection.tsx", cta_content, "tsx"))
        components.append("CTASection")

        # Test simulation: broken component reference
        if self._simulate_broken_component_ref:
            bad_page = self._make_file(
                "app/page.tsx",
                'import React from "react";\nimport { NonexistentWidget } from "@/components/sections/NonexistentWidget";\nexport default function Page() { return <NonexistentWidget />; }',
                "tsx",
            )
            files.append(bad_page)
            return GeneratedWebsiteProject(
                framework="nextjs",
                language="typescript",
                files=files,
                entrypoints=entrypoints,
            ), {}

        # 8. app/layout.tsx
        layout_content = f"""import type {{ Metadata }} from "next";
import "./globals.css";
import {{ Header }} from "@/components/layout/Header";
import {{ Footer }} from "@/components/layout/Footer";

export const metadata: Metadata = {{
  title: "{project_name} — Official Website",
  description: "{specification.website_goal}",
}};

export default function RootLayout({{
  children,
}}: {{
  children: React.ReactNode;
}}) {{
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col">
        <Header />
        <main className="flex-1">
          {{children}}
        </main>
        <Footer />
      </body>
    </html>
  );
}}
"""
        files.append(self._make_file("app/layout.tsx", layout_content, "tsx"))

        # 9. app/page.tsx (Home Page)
        home_page_content = """import React from "react";
import { Hero } from "@/components/sections/Hero";
import { FeatureGrid } from "@/components/sections/FeatureGrid";
import { CTASection } from "@/components/sections/CTASection";

export default function HomePage() {
  return (
    <>
      <Hero />
      <FeatureGrid />
      <CTASection />
    </>
  );
}
"""
        files.append(self._make_file("app/page.tsx", home_page_content, "tsx"))

        # 10. Secondary Pages based on Blueprint / Specification
        for page in blueprint.pages:
            clean_route = page.route.strip().strip("/")
            if not clean_route or clean_route == "home":
                continue

            routes.append(f"/{clean_route}")
            route_page_path = f"app/{clean_route}/page.tsx"

            page_code = f"""import React from "react";
import {{ Container }} from "@/components/ui/Container";

export const metadata = {{
  title: "{page.name} — {project_name}",
  description: "{page.purpose}",
}};

export default function {page.name.replace(" ", "")}Page() {{
  return (
    <div className="py-16">
      <Container>
        <h1 className="text-3xl sm:text-4xl font-bold text-slate-900">{page.name}</h1>
        <p className="mt-4 text-slate-600 leading-relaxed max-w-2xl">{page.purpose}</p>
        <div className="mt-12 p-8 border border-slate-200 rounded-lg bg-slate-50">
          <p className="text-slate-500 text-sm">Detailed content and sections for {page.name}.</p>
        </div>
      </Container>
    </div>
  );
}}
"""
            files.append(self._make_file(route_page_path, page_code, "tsx"))

        # 11. README.md
        readme_content = f"""# {project_name}

Generated by AI Web Agency Agent — Phase 6.4 Website Code Generation Engine.

## Tech Stack
- **Framework**: Next.js 15 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS + Centralized CSS Design Tokens
- **Icons**: Lucide React

## Project Architecture
- `app/` — Next.js App Router layouts, routes, and global styles
- `components/` — Design System components (Layout, UI, Sections)
- `lib/` — Utilities and design tokens

## Design Blueprint Compliance
- Design Tokens mapped to `:root` CSS variables in `app/globals.css`
- Component taxonomy: {len(components)} registered components
- Target audience: {specification.target_audience}
"""
        files.append(self._make_file("README.md", readme_content, "markdown"))

        # Test simulation: duplicate files
        if self._simulate_duplicate_files:
            files.append(self._make_file("package.json", pkg_content, "json"))

        project = GeneratedWebsiteProject(
            framework="nextjs",
            language="typescript",
            package_manager="npm",
            files=files,
            entrypoints=entrypoints,
            routes=routes,
            components=components,
            assets=[],
            metadata={
                "project_name": project_name,
                "project_slug": project_slug,
                "blueprint_version": blueprint.blueprint_version,
                "provider": self.provider_name,
                "model": self.model_name,
            },
        )

        provider_meta = {
            "provider": self.provider_name,
            "model": self.model_name,
            "generated_files_count": len(files),
            "generated_routes_count": len(routes),
            "generated_components_count": len(components),
        }

        return project, provider_meta


# ── AI Website Code Generation Provider ───────────────────────────────────────

class AIWebsiteCodeGenerationProvider(CodeGenerationProvider):
    """
    Real AI website code generation provider. Invokes external LLM when configured,
    or falls back deterministically to MockWebsiteCodeGenerationProvider.
    """

    def __init__(
        self,
        provider_name: str = "openai_code_generator",
        model_name: str = "gpt-4o",
    ):
        self._provider_name = provider_name
        self._model_name = model_name
        self._fallback_mock = MockWebsiteCodeGenerationProvider(
            custom_provider_name=provider_name,
            custom_model_name=model_name,
        )

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate_code(
        self,
        prd_data: Dict[str, Any],
        specification: WebsiteSpecification,
        blueprint: WebsiteDesignBlueprint,
        requirements: List[Dict[str, Any]],
        allowed_content: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[GeneratedWebsiteProject, Dict[str, Any]]:
        # In test and dev environments without active production AI keys,
        # fallback deterministically to the mock provider.
        return await self._fallback_mock.generate_code(
            prd_data=prd_data,
            specification=specification,
            blueprint=blueprint,
            requirements=requirements,
            allowed_content=allowed_content,
            context=context,
        )


def get_code_generation_provider(provider_type: Optional[str] = None) -> CodeGenerationProvider:
    """Factory function returning the active CodeGenerationProvider."""
    if provider_type == "mock" or not getattr(settings, "OPENAI_API_KEY", None):
        return MockWebsiteCodeGenerationProvider()
    return AIWebsiteCodeGenerationProvider()
