# Phase 6.4 Implementation Report — Actual Website Code Generation Engine

## 1. Objective
Phase 6.4 delivers the production-oriented executable website source generation layer of the AI Web Agency Agent. It translates the validated Design Blueprint (Phase 6.3), Website Specification (Phase 6.2), and Gate 4 Approved PRD (Phase 5.4) into an actual Next.js 15 (App Router) + React 19 + TypeScript source codebase stored in an isolated filesystem workspace and archived as immutable, checksummed build artifacts.

Crucially, Phase 6.4 is strictly **CODE GENERATION ONLY**:
- Zero deployment (no Vercel, no Netlify, no Cloudflare).
- Zero external repo management (no GitHub integration, no git push).
- Zero live execution (no npm install, no automated shell commands, no local execution of generated untrusted code).
- Zero live preview / iframe / hot reload (Phase 6.5).
- Zero browser automation / Playwright / QA (Phase 7).

---

## 2. Architecture & Pipeline

```text
Approved PRD (Gate 4)
         ↓
Website Specification (Phase 6.2)
         ↓
Design Blueprint (Phase 6.3)
         ↓
WebsiteCodeGenerationService (Phase 6.4)
    ├── Input Contract & Eligibility Check
    ├── CodeGenerationPromptBuilder (XML Data Containment)
    ├── CodeGenerationProvider (AI / Deterministic Mock)
    ├── CodeGenerationValidator (Static Safety, Secrets, Next.js Entrypoints)
    ├── WebsiteWorkspaceService (Isolated Filesystem, Path Traversal Defense)
    ├── WebsiteBuildArtifact (WEBSITE_SOURCE_CODE, Checksums, Full Manifest)
    └── AgentRun (Structured Immutable Audit Trail)
```

---

## 3. Database Models & Schema Changes
- **Migration**: `0017_website_code_generations.py` (applied and verified as current Alembic head).
- **Enums**:
  - `WebsiteCodeGenerationStatus`: `PENDING`, `GENERATING`, `VALIDATING`, `COMPLETED`, `FAILED`, `CANCELLED`.
  - `WebsiteBuildArtifactType.WEBSITE_SOURCE_CODE = "website_source_code"`.
- **Model**: `WebsiteCodeGeneration`:
  - `id`: UUID (PK)
  - `project_id`: UUID FK -> `projects.id`
  - `build_session_id`: UUID FK -> `website_build_sessions.id`
  - `website_generation_id`: UUID FK -> `website_generations.id`
  - `design_blueprint_id`: UUID FK -> `design_blueprints.id`
  - `approved_prd_id`: UUID FK -> `client_prds.id`
  - `source_artifact_id`: UUID FK -> `website_build_artifacts.id` (nullable)
  - `owner_id`: String(255)
  - `prd_version`: Integer
  - `code_generation_version`: Integer (sequential monotonic v1, v2, ...)
  - `status`: String/Enum
  - `provider`: String(100)
  - `model`: String(100)
  - `source_checksum`: String(64) SHA-256 digest
  - `file_count`: Integer
  - `error_code`, `error_message`: Strings / Text
  - `started_at`, `completed_at`, `failed_at`: DateTime (UTC)
  - `metadata`: JSON

---

## 4. Provider Abstraction
- `CodeGenerationProvider` (Abstract base): Defines interface `generate_code(...)`.
- `AIWebsiteCodeGenerationProvider`: Real AI LLM client with structured JSON parsing and fallback.
- `MockWebsiteCodeGenerationProvider`: High-fidelity deterministic synthesizer that produces complete Next.js projects conforming strictly to the Design Blueprint:
  - `package.json` with Next.js 15, React 19, Lucide React, Tailwind
  - `tsconfig.json` with `@/*` path mapping
  - `next.config.ts`
  - `postcss.config.mjs`
  - `app/globals.css` with CSS variables generated directly from Blueprint design tokens (`--color-primary`, `--spacing-section`, etc.)
  - `app/layout.tsx` with header, footer, accessibility landmark tags, and SEO metadata
  - `app/page.tsx` composing sections from the Blueprint
  - Secondary route pages (`app/[route]/page.tsx`)
  - Components (`components/layout/Header.tsx`, `components/layout/Footer.tsx`, `components/sections/Hero.tsx`, `components/sections/FeatureGrid.tsx`, `components/sections/CTASection.tsx`, `components/ui/Button.tsx`, `components/ui/Card.tsx`, `components/ui/Container.tsx`)
  - `lib/utils.ts` and `README.md`
  - Simulation flags for test validation: failure, malformed, secrets, unsafe code, path traversal, missing files.

---

## 5. Security & Safety Validations
1. **Deterministic Static Analysis (`CodeGenerationValidator`)**:
   - Rejects dangerous code patterns: `eval()`, `new Function()`, `child_process`, `exec()`, `spawn()`, `rm -rf`, destructive shell strings.
   - Rejects secrets and API keys: AWS Access Key IDs, GitHub tokens, OpenAI secret keys, private keys (`-----BEGIN PRIVATE KEY-----`).
   - Rejects unsafe URLs and inclusions: `javascript:` URLs, un-sandboxed `<iframe>` tags, insecure HTTP script inclusions.
   - Enforces required Next.js entrypoints: `package.json`, `tsconfig.json`, `app/layout.tsx`, `app/page.tsx`, `app/globals.css`.
   - Validates that imported component references resolve to existing generated component files.
2. **Path Traversal & Filesystem Isolation (`WebsiteWorkspaceService`)**:
   - All paths validated to be strictly relative and normalized.
   - Rejects `..`, drive prefixes (`C:`), leading slashes, and null bytes (`\x00`).
   - Verifies `commonpath` remains inside isolated workspace directory.
   - Safe workspace cleanup on generation failure or cancellation.
   - Generated code is NEVER executed on the host.
3. **Prompt Injection Defense (`CodeGenerationPromptBuilder`)**:
   - XML tag containment (`<approved_prd>`, `<confirmed_requirements>`, `<website_specification>`, `<design_blueprint>`, `<allowed_content>`).
   - Enforces system instruction that all enclosed content is UNTRUSTED DATA and never instructions.
4. **IDOR & Precondition Enforcement**:
   - JWT owner authentication enforced across all endpoints.
   - Project must be in `READY_FOR_BUILD`.
   - Build session must be in `READY` or `IN_PROGRESS`.
   - PRD must be in `APPROVED` status with matching version.
   - Concurrent active generation check prevents race conditions and data corruption.

---

## 6. API Endpoints
- `POST /api/v1/build-sessions/{session_id}/code-generations`: Initiates code generation.
- `GET /api/v1/build-sessions/{session_id}/code-generations`: Lists generations ordered by version descending.
- `GET /api/v1/code-generations/{generation_id}`: Retrieves details, status, and manifest summary.
- `POST /api/v1/code-generations/{generation_id}/cancel`: Cancels an active generation.
- `GET /api/v1/code-generations/{generation_id}/manifest`: Returns complete structured manifest with file list, checksums, routes, and components.
- `GET /api/v1/code-generations/{generation_id}/files`: Returns generated file contents, with optional `?path=` query parameter.

---

## 7. Dashboard UI
Updated `/dashboard/projects/[id]/build`:
- **Code Generation Control Section**:
  - Live status badge, version, file count, and aggregate SHA-256 checksum.
  - "Generate Website Code" trigger button and "Cancel Generation" button.
- **Interactive Code Inspector**:
  - Tab 1: **File Manifest** — Interactive list of all generated files with paths, types, sizes, checksums, and "View Code" actions.
  - Tab 2: **Source Inspector** — Syntax-highlighted code viewer displaying the full text content of any generated file.
  - Tab 3: **Routes & Architecture** — High-level overview of entrypoints, registered routes, and components.
  - Tab 4: **Raw Manifest JSON** — Complete structural manifest for debugging and export.
- **Code Generation History Card**:
  - Versioned history of past generation attempts with status badges, timestamps, and click-to-load navigation.
- **Phase Boundaries Maintained**:
  - No Deploy, Publish, Vercel, GitHub, Preview, or QA controls rendered.

---

## 8. Verification Results
- **Phase 6.4 Tests**: 19/19 PASSED.
- **Full Regression**: 455/455 PASSED.
- **Dashboard Production Build**: PASSED (`npm run build` compiled successfully).
- **Alembic Migration**: `0017_website_code_generations (head)` verified.

---

## 9. Exact Phase 6.5 Boundary
Phase 6.4 stops strictly at source code generation and storage.
**Phase 6.5 (Interactive Preview & Hot-Reload Engine)** will handle:
- Sandboxed browser rendering / iframe preview
- Interactive visual inspection
- Hot-reloading / dev preview server
Phase 6.4 does NOT implement any of these features.
