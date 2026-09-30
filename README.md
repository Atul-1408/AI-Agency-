# AI Web Agency Agent

> Semi-autonomous AI system for lead research, personalized outreach, client intelligence, website generation, QA, and deployment. **The human owner remains in full control.**

---

## Current Status: Phase 2 — Lead Research Agent ✅
- Phase 1: Foundation ✅
- Phase 2: Lead Research Agent ✅
  - Pluggable discovery providers (`GooglePlacesProvider`, `ManualEntryProvider`)
  - SSRF-protected, crawl-delay-compliant `WebsiteAuditorTool` (objective findings only)
  - Public corporate contact finder (`PublicContactFinderTool`) with verified MX status
  - Deterministic qualification scoring (0–100) & duplicate detection
  - Human approval gate & Next.js Lead Pipeline Dashboard (`/dashboard/leads`)

## Quick Start

### Prerequisites

- Node.js ≥ 20
- Python 3.11
- Docker + Docker Compose
- npm ≥ 10

### 1. Clone and install

```bash
git clone <repo>
cd agen
npm install
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your keys
```

### 3. Start infrastructure

```bash
docker compose up db redis -d
```

### 4. Install Python deps and run migrations

```bash
cd apps/api
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
alembic upgrade head
```

### 5. Start the API

```bash
cd apps/api
uvicorn main:app --reload
# API docs: http://localhost:8000/api/docs
```

### 6. Start the worker

```bash
cd apps/api
arq workers.main.WorkerSettings
```

### 7. Start the dashboard

```bash
cd apps/dashboard
cp .env.local.example .env.local
npm run dev
# Dashboard: http://localhost:3000
```

---

## Architecture

```
apps/
├── dashboard/     Next.js 14 owner dashboard
└── api/           FastAPI backend + ARQ workers

Key files:
  apps/api/models/__init__.py     — Database models
  apps/api/agents/               — Agent implementations
  apps/api/workers/main.py       — ARQ job queue
  apps/api/routers/              — API endpoints
```

## Safety Rules

- Max 50 emails/day (configurable)
- Duplicate detection on all leads
- Opt-out/suppression list
- Reply detection stops outreach
- All agent actions logged
- **Website deployments require explicit owner approval**

---

## License

Private — not for redistribution.
