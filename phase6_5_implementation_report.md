# Phase 6.5 Implementation Report: Live Preview & Iterative Website Editing Engine

**AI Web Agency Agent — Production Milestone**  
**Completed & Validated:** October 2026  
**Status:** Complete & Locked. Hard Scope Respected.

---

## 1. Executive Summary & Objective

Phase 6.5 delivers the **Live Preview and Iterative Website Editing Engine** for the AI Web Agency Agent, bridging the gap between validated Next.js source code generation (Phase 6.4) and production readiness (Phase 6.6+).

### Core Pipeline Flow:
```
Validated Next.js Source Code (Phase 6.4)
        ↓
Isolated Preview Workspace
        ↓
Live Website Preview (Sandboxed CSP Iframe)
        ↓
Owner Requests Edit ("Make the hero darker", "Change CTA text")
        ↓
AI Analyzes Request with XML Prompt Boundary Containment
        ↓
Controlled Minimal Source Modification (Rule 12: Targeted Files Only)
        ↓
Deterministic Static Re-Validation (CodeGenerationValidator Pipeline)
        ↓
New Immutable Version (v1 → v2 → v3...)
        ↓
Updated Live Preview
```

---

## 2. Hard Scope & Safety Enforcement

### Strictly Enforced Safeguards:
- **Zero Production Deployment:** No Vercel, Netlify, or AWS production hosting endpoints exist.
- **Zero GitHub Integration:** No `git push`, PR creation, or external repo connections.
- **Zero Browser QA / Autonomous Testing:** Playwright, Cypress, and Lighthouse testing remain strictly reserved for Phase 7.
- **Zero Autonomous External Communications:** No Gmail outreach, client notifications, or untrusted email dispatching.
- **Process & Workspace Isolation:** Generated website code runs in dedicated per-project, per-version workspace directories outside the main API process memory.
- **Secret Zero-Leakage:** Generated websites and preview iframes have **zero access** to host application secrets, database connection strings, OAuth tokens, or environment variables.

---

## 3. Architecture & Components

### 3.1 Preview Engine (`WebsitePreviewService`)
- **Workspace Isolation:** Clones generated Next.js project trees into isolated directories (`.agency_workspaces/previews/{project_id}/{preview_id}`).
- **Sandboxed Rendering:** Live preview iframe endpoint (`/api/v1/previews/{id}/render`) returns compiled HTML with strict Content-Security-Policy headers:
  - `Content-Security-Policy: default-src 'self' ...; frame-ancestors 'self' ...`
  - `X-Frame-Options: SAMEORIGIN`
  - `X-Content-Type-Options: nosniff`
- **Preview Lifecycle State Machine:**
  - `CREATED` → `STARTING` → `RUNNING` → `STOPPING` → `STOPPED`
  - Automatic expiration (`EXPIRED`) after TTL (default: 60 minutes) with on-demand cleanup and restart.

### 3.2 Iterative Editing Engine (`WebsiteEditingService`)
- **Minimal Change Rule:** AI modifies only the relevant component or token files (e.g. changing the Hero section modifies only `components/sections/Hero.tsx`), completely avoiding blind full-project regeneration and preventing regressions.
- **Prompt Defense & XML Containment (`WebsiteEditingPromptBuilder`):**
  - Strict boundary tagging:
    ```xml
    <approved_prd>...</approved_prd>
    <website_specification>...</website_specification>
    <design_blueprint>...</design_blueprint>
    <current_source>...</current_source>
    <owner_edit_request>...</owner_edit_request>
    ```
  - Full sanitization and closing-tag neutralization preventing prompt injection attacks.
- **Deterministic Static Re-Validation:** All proposed source changes pass through the Phase 6.4 `CodeGenerationValidator` (verifying Next.js structure, no path traversals, no forbidden APIs like `eval`, `child_process`, and no hardcoded API keys).
- **Atomic Application:** Edits are assembled and validated in a temporary staging workspace. If validation fails, changes are completely discarded and the active preview/source remains untouched.
- **Optimistic Concurrency Protection:** Every edit requires `base_version`. If a concurrent edit already incremented the version, requests are rejected with `409 Conflict`.

### 3.3 Versioning & Non-Destructive Rollback
- **Immutable Version History (`WebsiteEditVersion`):**
  - `v1` (Initial Code Generation) → `v2` (Hero Update) → `v3` (Sticky Header)
  - Every version retains its complete source tree, checksum, diff summary, and parent reference.
- **Non-Destructive Rollbacks:**
  - Rolling back to `v2` from `v4` creates a brand new snapshot release `v5` containing the exact code from `v2`.
  - Historical records `v1`, `v2`, `v3`, `v4` are **never deleted or overwritten**.

---

## 4. Database Schema & Migration

### Alembic Migration:
- **File:** `0018_website_previews_and_edits.py`
- **Head:** `0018_website_previews_and_edits (head)`
- **Tables Introduced:**
  1. `website_previews`:
     - Tracks preview lifecycle, ports, process references, workspace paths, TTLs, and tokens.
  2. `website_edit_sessions`:
     - Records owner editing instructions, status lifecycle (`PENDING`, `ANALYZING`, `GENERATING`, `VALIDATING`, `APPLIED`, `FAILED`, `CANCELLED`), diff summaries, and errors.
  3. `website_edit_versions`:
     - Immutable records storing sequential version numbers, parent version links, changed file lists, diff summaries, and workspace checksums.

---

## 5. API Endpoints

All endpoints require JWT owner authentication and enforce strict project and workspace ownership verification (IDOR defense):

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/projects/{project_id}/previews` | Create a new isolated preview instance |
| `GET` | `/api/v1/projects/{project_id}/previews` | List all previews for a project |
| `GET` | `/api/v1/previews/{preview_id}` | Retrieve preview details |
| `POST` | `/api/v1/previews/{preview_id}/start` | Start preview instance |
| `POST` | `/api/v1/previews/{preview_id}/stop` | Stop running preview instance |
| `POST` | `/api/v1/previews/{preview_id}/restart` | Restart preview instance |
| `GET` | `/api/v1/previews/{preview_id}/status` | Check preview runtime status & uptime |
| `GET` | `/api/v1/previews/{preview_id}/render` | Render sandboxed preview HTML (CSP-protected) |
| `POST` | `/api/v1/projects/{project_id}/edits` | Submit an iterative edit request |
| `GET` | `/api/v1/projects/{project_id}/edits` | List edit sessions for project |
| `GET` | `/api/v1/edits/{edit_id}` | Retrieve edit session status and diff |
| `POST` | `/api/v1/edits/{edit_id}/cancel` | Cancel an in-progress or pending edit |
| `GET` | `/api/v1/projects/{project_id}/versions` | List all immutable project versions |
| `GET` | `/api/v1/versions/{version_id}` | Retrieve version metadata and files |
| `POST` | `/api/v1/versions/{version_id}/rollback` | Rollback to version via non-destructive release |

---

## 6. Dashboard Interface

The project build dashboard (`/dashboard/projects/[id]/build`) has been expanded with three interactive, real-time cards:

1. **Live Preview Card:**
   - Real-time status badge (`RUNNING`, `STOPPED`, `STARTING`, `EXPIRED`).
   - Action controls: **Start**, **Stop**, **Restart**, and **Open in New Tab**.
   - Device viewport selector: **Desktop (100%)**, **Tablet (768px)**, **Mobile (375px)**.
   - Sandboxed iframe container loading `/api/v1/previews/{id}/render`.
2. **Iterative Website Editing Card:**
   - Change instruction input with quick prompt chips:
     - *"Make the hero darker with slate-950 background"*
     - *"Make the navigation header sticky with blur"*
     - *"Change the CTA button text to Claim Free Consultation"*
     - *"Reduce vertical spacing in services section"*
   - **Apply Change** button with real-time analysis, generation, and validation loading states.
   - Change summary display showing affected components, modified files, and diff summary.
3. **Version History & Rollback Card:**
   - Chronological release timeline (v1, v2, v3...).
   - Shows active version badge, checksum, creation timestamp, and change description.
   - **Rollback to Version** button with instant preview synchronization and immutable release generation.

---

## 7. Verification & Test Results

### 7.1 Phase 6.5 Targeted Test Suite (`test_phase6_5_previews_and_edits.py`)
- **16 of 16 tests passing (100%):**
  1. `test_preview_and_editing_require_owner_auth`: Enforces 401 on unauthenticated calls.
  2. `test_preview_and_editing_idor_protection`: Enforces 403 on cross-tenant / intruder requests.
  3. `test_preview_creation_and_lifecycle`: Create → Start → Status → Stop → Restart.
  4. `test_preview_expiration`: Automatically transitions expired previews to `EXPIRED`.
  5. `test_preview_render_security_headers`: Verifies CSP headers and iframe sandboxing.
  6. `test_mock_provider_minimal_change_rule`: Confirms minimal file touch (1-2 files per change).
  7. `test_prompt_injection_defense`: Validates XML escaping and instruction preservation.
  8. `test_successful_edit_creates_new_version`: v1 → v2 transition with preview sync.
  9. `test_stale_base_version_conflict`: Returns 409 Conflict when base version is outdated.
  10. `test_validation_failure_preserves_working_source`: 422 rejected, zero corruption.
  11. `test_non_destructive_rollback`: v2 rollback from v3 creates v4 without losing history.
  12. `test_edit_cancellation`: Cancels pending sessions safely.
  13. `test_phase_boundaries_strictly_enforced`: Prohibited endpoints (/deploy, /github, /vercel, /qa) return 404.
  14. `test_workspace_and_secret_isolation`: Zero leak of database or server secrets.
  15. `test_path_traversal_and_forbidden_api_rejection`: Rejects `../` and malicious Node imports.
  16. `test_audit_logging_recorded_for_all_lifecycle_events`: Verifies immutable audit records in `agent_runs`.

### 7.2 Full Regression Test Suite
- **Command:** `python -m pytest tests/ -q`
- **Result:** **471 passed in 126.11s (100% pass rate)** across all API test suites.

### 7.3 Frontend Production Build
- **Command:** `npm run build` in `apps/dashboard`
- **Result:** Passed with 0 TypeScript errors and optimized bundle generation.

### 7.4 Database Migration Head
- **Command:** `python -m alembic current`
- **Result:** `0018_website_previews_and_edits (head)` verified.

### 7.5 Whitespace & Git Quality
- **Command:** `git diff --check`
- **Result:** 0 whitespace or formatting issues.

---

## 8. Known Limitations & Exact Phase 6.6 Boundary

### Handled in Phase 6.5:
- In-memory/filesystem sandboxed preview rendering.
- Incremental source code editing and version rollbacks.
- Owner-authenticated dashboard controls.

### Explicit Phase 6.6 Boundary (Do NOT Start Yet):
- Complete Phase 6 End-to-End Audit & Verification.
- Final Gate Review before Phase 7 QA Automation.
- Autonomous operations, production deployment, and client communications remain strictly prohibited.
