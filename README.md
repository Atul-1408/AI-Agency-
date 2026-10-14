# AI Web Agency Agent

> Semi-autonomous AI system for lead research, personalized outreach, client intelligence, website generation, automated QA, and deployment. **The human owner remains in full control.**

---

## Current Status: Phase 7 — Automated QA Agent & Complete Dashboard UI Upgrade ✅

- **Phase 1: Foundation & Orchestration ✅**
  - Multi-agent coordinator, state machines, and structured audit telemetry (`AgentRun`).
  - Owner authentication, JWT tokens, and deterministic Gate 1 approval gates.
- **Phase 2: Lead Research Agent ✅**
  - Pluggable discovery providers (`GooglePlacesProvider`, `ManualEntryProvider`).
  - SSRF-protected, crawl-delay-compliant `WebsiteAuditorTool` (objective findings only).
  - Public corporate contact finder (`PublicContactFinderTool`) with verified MX status.
  - Deterministic qualification scoring (0–100) & duplicate detection.
  - Human approval gate & Next.js Lead Pipeline Dashboard (`/dashboard/leads`).
- **Phase 3: Outreach Agent ✅**
  - AI-powered personalized email drafting anchored to lead audit findings.
  - Gate 2 Human-in-the-loop owner approval gatekeeper (`/dashboard/outreach`).
  - Real Gmail API dispatch, thread tracking, and suppression lists.
- **Phase 4: Follow-up Sequences & Reply Detection ✅**
  - Multi-touch automated follow-up sequences with jitter-protected smart delays.
  - Inbound reply detection, thread continuation, and automatic opt-out suppression.
- **Phase 5: Client Intelligence & PRD Pipeline ✅**
  - Client conversation thread parsing and requirement extraction.
  - Structured PRD generation with sitemaps, tech stack, and design archetypes (`/dashboard/client-intelligence/prds`).
  - Gate 4 PRD approval promoting clients to active projects (`/dashboard/projects`).
- **Phase 6: Website Builder Platform ✅**
  - **Phase 6.1–6.2:** Build session lifecycle, structured `WebsiteSpecification` generation.
  - **Phase 6.3:** Complete design tokens, components taxonomy, and `WebsiteDesignBlueprint`.
  - **Phase 6.4:** Next.js + Tailwind source code generation, manifest inspection, file viewer.
  - **Phase 6.5:** Live preview sandbox, multi-versioning, iterative AST editing, and 1-click rollback.
- **Phase 7: Automated QA Agent + Complete Dashboard Upgrade ✅**
  - 8-point automated audit engine (build integrity, routes, broken links, responsive viewports, WCAG 2.1 AA a11y, SEO metadata, security/secrets sanitization, performance).
  - Strict deployment gatekeeping: blocker and high findings prevent premature deployment.
  - Automated AI repair loop advancing code versions and auto-resolving defects.
  - Complete luxury dark command-center dashboard UI (`#0B0A0C`, `#171519`, `#E8B968`, `#39C98A`, `#8B6FB8`).
- **Phase 8: Deployment & Hosting ⏳ (Upcoming)**
  - One-click deployment to Vercel with GitHub repo synchronization and custom domain SSL.

---

## Dashboard Navigation & Capabilities

- **Overview:** `/dashboard` — Real-time live metrics across projects, leads, approvals, and agent telemetry.
- **Leads:** `/dashboard/leads` — Prospect discovery, website audits, qualification scoring, and approval pipeline.
- **Outreach:** `/dashboard/outreach` — Draft review, approval gate 2, email dispatch, and follow-up sequences.
- **Client PRDs:** `/dashboard/client-intelligence/prds` — Requirement gathering, sitemaps, and Gate 4 PRD approval.
- **Projects & Builder:** `/dashboard/projects` — Active projects, build sessions, and workspace controls.
- **Website Workspace:** `/dashboard/projects/[id]/build` — Specs, design blueprints, code generator, live previews, iterative editing, and Phase 7 Automated QA.
- **Approvals:** `/dashboard/approvals` — Centralized human-in-the-loop review for all outbound touches.
- **Agent Runs:** `/dashboard/runs` — Comprehensive execution history, telemetry, and structured audit logs.
- **Settings:** `/dashboard/settings` — Gmail OAuth, provider credentials, and system configuration.

---

## Quick Start

### Prerequisites

- Node.js ≥ 20
- Python 3.11+
- Docker + Docker Compose
- npm ≥ 10

### 1. Clone and install dependencies

```bash
git clone <repo>
cd agen
npm install
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your configuration
```

### 3. Start database & Redis infrastructure

```bash
docker compose up db redis -d
```

### 4. Install Python dependencies and run database migrations

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
alembic upgrade head
```

### 5. Start the backend API

```bash
cd apps/api
uvicorn main:app --reload --port 8000
# API docs: http://localhost:8000/api/docs
```

### 6. Start the background worker

```bash
cd apps/api
arq workers.main.WorkerSettings
```

### 7. Start the dashboard

```bash
cd apps/dashboard
npm run dev
# Dashboard: http://localhost:3000
```

---

## Testing & Quality Assurance

### Run full backend test suite (485+ tests):

```bash
cd apps/api
.venv\Scripts\pytest tests/ -v
```

### Run frontend production build & type checks:

```bash
cd apps/dashboard
npm run build
```

---

## Safety & Governance Rules

- Human-in-the-loop owner approval required before any outreach or deployment
- SSRF-safe crawling with crawl delays and private IP blocking
- Duplicate lead detection and verified MX email checks
- Rate-limited outreach (configurable max emails/day)
- Global suppression list and automatic opt-out handling
- Automatic outreach cessation upon client reply detection
- Zero secret leakage: automated static scanning blocks exposed API keys
- Immutable versioning and non-destructive rollbacks on all generated websites

---

## License

Private — not for redistribution.
