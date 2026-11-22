# Production Deployment & Operations Guide

> Complete production runbook for deploying, configuring, and maintaining the AI Web Agency Agent platform.

---

## Architecture Overview

```
                      ┌──────────────────────────────────────┐
                      │    Cloudflare / Nginx Reverse Proxy   │
                      │         (SSL Termination :443)       │
                      └──────────────────┬───────────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 │                                               │
                 ▼ :3000                                         ▼ :8000
    ┌─────────────────────────┐                     ┌─────────────────────────┐
    │  Next.js 16 Dashboard   │──(REST / JSON API)─▶│   FastAPI Backend API   │
    │  Standalone Container   │                     │  (Uvicorn Multi-Worker) │
    └─────────────────────────┘                     └────────────┬────────────┘
                                                                 │
                                         ┌───────────────────────┴───────────────────────┐
                                         │                                               │
                                         ▼ :5432                                         ▼ :6379
                            ┌─────────────────────────┐                     ┌─────────────────────────┐
                            │      PostgreSQL 16      │                     │         Redis 7         │
                            │   (Persistent Storage)  │                     │   (ARQ Task Queue)      │
                            └─────────────────────────┘                     └────────────┬────────────┘
                                                                                         │
                                                                                         ▼
                                                                            ┌─────────────────────────┐
                                                                            │   ARQ Background Worker │
                                                                            │   (Long-Running Tasks)  │
                                                                            └─────────────────────────┘
```

---

## 1. Secrets & Environment Setup (Step 4)

### 1.1 Generate Cryptographic Production Secrets
Run the included secrets generator:
```bash
python scripts/generate_production_secrets.py
```
This generates cryptographically secure 64-character hex keys for `APP_SECRET`, `NEXTAUTH_SECRET`, AES-256-GCM encryption keys, and a bcrypt password hash.

### 1.2 Prepare Environment File
Copy the production environment template:
```bash
cp .env.production.example .env.production
```
Fill in:
- `APP_SECRET`: 64-character hex string.
- `NEXTAUTH_SECRET`: 64-character hex string.
- `OWNER_EMAIL`: Your operational email address.
- `OWNER_PASSWORD_HASH`: Your bcrypt password hash.
- `DATABASE_URL`: `postgresql+asyncpg://<user>:<password>@<host>:5432/<dbname>`
- `REDIS_URL`: `redis://:<password>@<host>:6379/0`
- `CORS_ORIGINS`: `["https://yourdomain.com"]`

---

## 2. Infrastructure Deployment (Step 1)

### Option A: Complete Docker Compose Production Stack (Self-Hosted / VPS)

The production stack orchestrates PostgreSQL 16, Redis 7, FastAPI API, ARQ Worker, and the Next.js Dashboard.

1. **Start the stack:**
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
   ```

2. **Verify running containers:**
   ```bash
   docker compose -f docker-compose.prod.yml ps
   ```

3. **Check database migrations:**
   Migrations run automatically on container startup via `apps/api/entrypoint.sh`. To run manually:
   ```bash
   docker compose -f docker-compose.prod.yml exec api alembic upgrade head
   ```

4. **Inspect live logs:**
   ```bash
   docker compose -f docker-compose.prod.yml logs -f api worker dashboard
   ```

---

### Option B: Cloud Platform (Render / Railway / Supabase + Upstash)

1. **Database & Cache:**
   - Provision a PostgreSQL database (e.g. Supabase, Neon, or Render Postgres).
   - Provision Redis (e.g. Upstash or Render Redis).
2. **Backend API:**
   - Deploy as Python web service pointing to `DATABASE_URL` and `REDIS_URL`.
   - Build: `pip install -r apps/api/requirements.txt`
   - Start: `cd apps/api && alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port $PORT --workers 4`
3. **Background Worker:**
   - Deploy background worker service.
   - Start: `cd apps/api && arq workers.main.WorkerSettings`
4. **Dashboard:**
   - Deploy Next.js web service pointing to `NEXT_PUBLIC_API_URL=https://api.yourdomain.com`.
   - Build: `npm install && npm run build --workspace=@agen/dashboard`
   - Start: `cd apps/dashboard && npm run start`

---

## 3. Production Health & Readiness Verification

Once deployed, verify all endpoints:

1. **System Health Check (HTTP 200):**
   ```bash
   curl -i https://api.yourdomain.com/api/v1/health
   ```
   Expected response:
   ```json
   {
     "status": "ok",
     "version": "0.1.0",
     "environment": "production",
     "services": {
       "database": {"status": "ok"},
       "redis": {"status": "ok"}
     }
   }
   ```

2. **Comprehensive Subsystem Readiness Audit:**
   ```bash
   curl -i -H "Authorization: Bearer <OWNER_TOKEN>" https://api.yourdomain.com/api/v1/system/readiness
   ```
   Audits:
   - Database dialect (PostgreSQL vs SQLite)
   - Redis worker connectivity
   - AI engine state
   - Storage isolation & workspace directory write access
   - Orchestrator 24-stage pipeline readiness

---

## 4. Production Security & Safeguards Enforced

- **HTTP Security Headers:** Injected on all API responses (`X-Content-Type-Options: nosniff`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security`).
- **Distributed Request Tracing:** Unique `X-Correlation-ID` header injected and bound to Structlog contextvars.
- **Secret Redaction:** Structlog scrub processor automatically sanitizes passwords, API keys, bearer tokens, and credentials from console and file logs.
- **Human Approval Gates:** Outbound emails (Gate 2) and live deployments (Gate 5) require explicit owner approval and cannot be bypassed programmatically.
- **Anti-Spam Controls:** 72-hour cooldown per lead, daily send rate limits (`MAX_EMAILS_PER_DAY=30`), and automatic unsubscribe keyword detection.
- **Directory Traversal Defense:** Isolated workspace builder enforces `os.path.commonpath` checks on all disk writes and preview renders.

---

## 5. Maintenance & Disaster Recovery

- **PostgreSQL Database Backup:**
  ```bash
  docker compose -f docker-compose.prod.yml exec -T db pg_dump -U agen agen > backup_$(date +%Y%m%d).sql
  ```
- **Database Restore:**
  ```bash
  cat backup_file.sql | docker compose -f docker-compose.prod.yml exec -T db psql -U agen agen
  ```
- **Redis Queue Flush (Emergency Only):**
  ```bash
  docker compose -f docker-compose.prod.yml exec redis redis-cli -a <password> flushall
  ```
