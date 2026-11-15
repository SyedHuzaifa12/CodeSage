# CodeSage — Project Memory

Purpose: a clean, durable briefing for any future session (human or AI) so work can resume with full context.
Last updated: 2026-11-15. Maintain this file whenever a decision, status, or measured fact changes.
Related: `CLAUDE.md` (engineering rules), `ARCHITECTURE_DECISIONS.md` (ADRs), `docs/SPRINT_LOG.md` (build progress),
`docs/DEPLOYMENT_AND_AUTH_PLAN.md` (current plan), `docs/ADR_DRAFTS_027-030.md` (proposed ADRs awaiting approval).

---

## 1. What this project is

- **CodeSage**: an AI Repository Intelligence Platform. It turns a GitHub repository into structured knowledge
  (AST symbols, call/import/dependency graph, embeddings) and answers natural-language questions about it with
  grounded evidence, a verification step, and a confidence score. Also generates onboarding/architecture reports.
- **Owner**: GitHub user `SyedHuzaifa12` — repo `https://github.com/SyedHuzaifa12/CodeSage`.
- **Owner's goal**: a portfolio-grade, real, end-to-end product to get hired by good product companies and to show
  founders/managers genuine engineering depth (architecture decisions, measured trade-offs, CI/CD, security).
  Hiring-manager-facing material matters: README, architecture diagram, eval numbers, live demo, ADR log.
- **Hard constraint for deployment**: everything must be **free** and **no credit card** (owner has no card).

## 2. Architecture (frozen rules live in CLAUDE.md — summary only)

- **Modular monolith** (ADR-001), FastAPI backend, Next.js frontend, Streamlit devtools (dev only).
- Data stores (ADR-006): **PostgreSQL** (metadata + lightweight knowledge graph + reports + conversations + job status),
  **Qdrant** (single collection `repository_chunks`, 384-dim cosine), **Redis** (cache/locks; Celery broker on DB 1 in
  local compose mode per ADR-026).
- Parsing: Tree-sitter (Python, JS, TS, Java). Embeddings: BAAI/bge-small-en-v1.5 via fastembed (ONNX, local).
  Orchestration: LangGraph single linear graph. LLM: Groq primary (`openai/gpt-oss-120b`), Ollama fallback (local only).
- Pipeline: clone -> workspace scan -> parse -> intelligence -> knowledge (chunk, embed, upsert) -> retrieval -> AI engine
  (intent -> retrieval -> evidence -> context -> reasoning -> verification -> format) -> reports.
- Module layout: `backend/app/{api,core,db,models,schemas,repository,ingestion,knowledge,retrieval,ai,reports,services,
  middleware,exceptions,shared,utils,tests}`. Every module except `ai/` uses `api.py/service.py/repository.py/schemas.py/
  exceptions.py/utils.py`. Knowledge module is the only owner of vector/graph storage access.
- API: REST under `/api/v1`, uniform envelope `{success, message, data|errors}`. Health: `/health`, `/health/live`
  (no downstream I/O — use for pings), `/health/ready`.
- Indexing: **Celery** worker (ADR-026, supersedes ADR-011 BackgroundTasks), Redis broker, per-repo Redis lock
  (`ingestion/indexing_lock.py`), prefork pool, `--concurrency` default 4, `-Q indexing`. Embedding model pre-warmed per
  worker process (first ONNX inference otherwise costs up to ~125 s — measured in ADR-026).
- Frontend: Next.js 14 App Router, React 18, TanStack Query, React Flow, Mermaid, Tailwind. Pure API client; backend URL via
  `NEXT_PUBLIC_API_BASE_URL` (baked at build time). Dynamic routes `/r/[repositoryId]/...` (no static export possible).
  `frontend/scripts/run-normalized.js` wraps npm scripts (Windows path-casing workaround — must be checked on Linux CI).

## 3. Current status (as of 2026-11-15)

- Sprints 0.1–7 complete (skeleton, infra, foundation, DB, repository, workspace, parsing, intelligence, knowledge,
  retrieval, AI engine, reports, production frontend) + ADR-025 (pipeline perf) + ADR-026 (Celery) — all merged to `master`
  (`1cd74e7`, PR #2). Deployment/CI is **not started**: no `.github/`, no hosted deployment, root `README.md` is **empty (0 bytes)**.
- Git: working branch **`feat/auth-guest`** (from `master`). Old branches `feat/frontend`, `feat/indexing-performance`
  are merged and can be deleted. Nothing from the current phase has been pushed.
- Tests: pytest (`backend/app/tests`, asyncio session-scoped loop) incl. integration tests needing Postgres/Redis/Qdrant and
  a live-Groq smoke test (`test_ai_live_smoke.py`, exclude in CI); frontend vitest (`frontend/test`).
  Eval scripts: `backend/scripts/{retrieval_eval,ai_eval,reports_eval}.py`.
- Local dev appears to run Python 3.14; Docker image is Python 3.12-slim. CI should use 3.12.

## 4. Known gaps and risks in the code (verified by reading it)

1. ~~No authentication~~ — **implemented in Phase 2 (branch `feat/auth-guest`, uncommitted)**, see section 10. Consequence: the Next.js
   frontend and the Streamlit devtools send no tokens, so they get **401 on everything except `/health*` until Phase 3 / a devtools
   update**. Rows created before accounts have `owner_id = NULL` and are invisible through the API (re-index them).
2. **`POST /repositories` clones synchronously inside the API request** (GitPython, blocking the event loop) and runs the
   workspace scan in the API process; indexing (Celery) then reads that clone from disk, so API and worker must share a
   disk (docker-compose shares the `repository_storage` volume). Blocks any split-host deployment as-is.
3. Backend config is host/port only: **no SSL for Postgres, no TLS for Redis, no Qdrant URL/API key** (cannot talk to
   Neon / Upstash / Qdrant Cloud yet). Alembic reads the same `DatabaseSettings.async_dsn`.
4. Startup **fails fast** if Postgres schema, Redis, or Qdrant are unreachable (`core/lifespan.py`). Migrations are manual.
5. Celery broker on Redis polls constantly -> would burn Upstash free quota; `redis_db`/Celery DB index 1 may be unsupported
   on Upstash (unverified).
6. Embedding cache in Redis stores each vector as a CSV string (~7–8 KB per chunk, 30-day TTL) -> large Redis footprint.
7. Logs write to file by default (`LOG_TO_FILE=true`) — disable on hosts with ephemeral/in-memory disk.
8. `ALLOWED_HOSTS=*`, `CORS_ORIGINS=http://localhost:3000` defaults — must be set explicitly in production.
9. `.env` holds real secrets (e.g., Groq key) and is gitignored; use a **new** Groq key for production.
10. `CLAUDE.md` and `docs/` are gitignored (not visible on GitHub). `ARCHITECTURE_DECISIONS.md` is tracked.

## 5. Measured facts (use these, don't guess)

- Memory (owner's Windows laptop, working set, one run): import app ~200 MB; + bge-small model ~300 MB; after embedding just
  8 chunks of 3000 chars ~460 MB (peak ~500 MB). Default `EMBEDDING_BATCH_SIZE=32`. => cannot run indexing in 512 MB.
- ADR-026 benchmark: two repos indexed concurrently on two worker processes = 1.9x speedup vs sequential (real CPUs).
  Celery speeds up *multiple repos at once*, not a single repo.
- Last fixed OOM: lockfiles / huge generated files crashing the ONNX embedder; now excluded + 512 KB cap.

## 6. Deployment research outcomes (Nov 2026; web sources, mostly third-party — re-verify before relying)

Constraint: free + no card. **No card-free host offers more than 512 MB RAM.**
- Rejected: Google Cloud Run (needs card; India: card/NetBanking, UPI only for qualified orgs), Modal (asked for a card),
  Fly.io (no free tier), Oracle (card), Hugging Face Spaces (Docker Spaces need PRO), Koyeb (conflicting card/restricted
  signups), Azure for Students (only enrolled students; India verification unreliable), GitHub Actions as compute
  (ToS risk: serverless/burden clauses), Cloudflare Tunnel from laptop (owner declined), full microservices on many free hosts
  (cold-start chains, no private network, contradicts ADR-001).
- **Render Free** (owner confirmed signup needs no card): 512 MB, ~0.1 CPU (third-party figure), sleeps after 15 min without
  inbound traffic (~1 min wake), 750 free instance hours/month/workspace, ephemeral disk, may restart anytime, no private-network
  ingress, no free background-worker type, Render's docs say free instances are not for production. Free Render Postgres expires
  after 30 days (not used).
- Neon free: 0.5 GB/project, 100 CU-hours/month, autosuspend, 10 branches. Do not ping `/health` (keeps Neon awake).
- Upstash free: 500K commands/month, 256 MB. Fine for cache/locks/rate limits; NOT for a Celery broker.
- Qdrant Cloud free: 1 GB RAM / 0.5 vCPU / 4 GB disk; suspends after 1 week idle, deleted after 4 weeks -> weekly keep-alive.
- Netlify free: credit-based (300/month per third-party sources); each prod deploy costs credits; Vercel Hobby is non-commercial.
- Cloudflare Workers AI: hosts `@cf/baai/bge-small-en-v1.5` (same model, 384 dims); free 10,000 neurons/day (~5.4M tokens/day by
  arithmetic from 1841 neurons per M tokens); cloudflare says no card needed. Verify at signup.

## 7. Decisions taken in this planning effort (details in the plan doc and ADR drafts)

- Auth: **guest-first, then login** — anyone may index 1 repo as a server-issued guest; further use requires GitHub login
  (**Path B**: GitHub OAuth as identity only; sessions are our own JWTs). Owner explicitly overrode the old "no OAuth / single-user"
  docs. Pre-indexed **demo repo = `expressjs/express`** (not CodeSage itself).
- Architecture: **one image, two roles** (`ROLE=api|indexer|all`), **Postgres-backed job queue** for the hosted mode,
  Celery retained only for local docker-compose. Hosted embeddings via **Cloudflare Workers AI**. Single-container fallback
  (`ROLE=all`) if only one host works.
- Hosting: Netlify (frontend) + Render Free x2 (API, indexer) + Neon + Upstash + Qdrant Cloud + Cloudflare Workers AI + Groq.
- Order: Phase 0 housekeeping (done) -> Phase 1 ADRs -> 2 auth backend -> 3 auth frontend + demo repo -> 4 hosted embeddings
  -> 5 role split -> 6 deployment prep -> 7 provision/deploy -> 8 CI/CD -> 9 hardening/polish.

## 8. Working agreements (follow these)

- **Architecture-First Policy** (CLAUDE.md): explain conflicts, recommend, and wait for explicit approval before changing
  architecture, folder structure, or technology. New ADRs start `Proposed`, become `Accepted` only on the owner's approval;
  never edit an accepted ADR's Decision/Rationale — supersede it with a new one.
- **Do not change anything without the owner's permission.** The owner approves phase by phase ("go Phase N").
- Do not push or commit unless asked. Conventional commits (`feat:`, `fix:`, `chore:`, `docs:`), present tense, say *why*.
  Commit-message trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Never commit secrets; `.env` stays local; `.env.example` is the tracked template.
- Honesty rule: label anything unverified as unverified; prefer measured numbers (see section 5).

## 10. Phase 2 (auth backend) — what exists now (uncommitted on `feat/auth-guest`)

- **Migration** `f5a1c3d9b7e2`: tables `users`, `refresh_tokens`; `repositories.owner_id` (FK users, RESTRICT, nullable for legacy rows)
  and `repositories.is_demo`. Verified up/down/up on a throwaway DB. **The dev DB still needs `alembic upgrade head`** (the app refuses
  to start until then; integration tests skip until then).
- **`app/core/security.py`**: pure JWT/refresh primitives (HS256 pinned, 15 min access; opaque 384-bit refresh tokens stored as SHA-256).
- **`app/auth/`** (new module): `api.py`, `service.py`, `repository.py`, `schemas.py`, `exceptions.py`, `dependencies.py`, `quota.py`,
  `turnstile.py`, `github.py`, `utils.py`. Routes: `POST /auth/guest`, `/auth/refresh`, `/auth/logout`, `GET /auth/github/authorize`,
  `POST /auth/github`, `GET /auth/me`, `POST /internal/cleanup-guests` (needs `X-Internal-Token`).
- **Ownership**: router-level `get_accessible_repository` on every `/repositories/{id}/...` router (404 for non-owners, identical to
  "not found"); `require_repository_write` on mutating routes (demo repos read-only except for admins). `/logs` is admin-only.
- **Quotas** (Redis fixed windows): guest 1 repo, daily question caps, per-IP guest creation, global daily guest-index cap, guest clone
  size/file caps. Question quota applies to `/ask` and `POST /reports/{type}` and is checked *after* the ownership check.
- **Config**: new `AuthSettings`; `Settings.production_problems()` makes any non-development environment refuse to start without a strong
  `JWT_SECRET`, Turnstile secret, GitHub OAuth trio, `INTERNAL_API_TOKEN` and `DEBUG=false`. Blank `KEY=` values mean "unset".
- **Deviations from the ADR-027 draft**: `trusted_proxy_hops` (int) instead of a boolean; staging is held to production rules; extra error
  codes `TOKEN_REUSED` and `SERVICE_UNAVAILABLE`; per-guest daily repository-attempt cap; refresh reuse has a 10 s grace window.
- **Not done yet (deliberately)**: clone *timeout* (moves with the clone into the indexer in Phase 5); frontend/devtools token handling
  (Phase 3); demo repo seeding (Phase 3); rate limit on `/auth/refresh`.
- **Known limitations**: access tokens stay valid up to 15 min after logout; two simultaneous repo creations by one guest can both pass the
  count check (bounded by attempt/global caps); `POST /repositories` still clones synchronously inside the request until Phase 5.
- **Tests**: 369 backend tests collected, 368 pass + 1 Windows-only skip, incl. 97 new ones (10 JWT, 28 quota/config, 12 external
  clients, 38 integration, 9 repository limits) covering (JWT attacks incl. `alg=none`, rotation/reuse,
  grace window, GitHub upgrade/merge, cleanup, IDOR across every sub-route, demo read-only, quotas, internal-token endpoint).
  Run them against a migrated DB: set `POSTGRES_DB` to a scratch database, `alembic upgrade head`, then `pytest`.
- **Side effects on the local machine**: `PyJWT` added to `backend/requirements.txt`; the venv was synced to requirements (installed
  `pathspec`, `celery` which were missing). A scratch Postgres DB and Redis DB 15 used for testing were removed afterwards.
- **Latent bug fixed on the way**: `remove_local_clone(Path(""))` would have `rmtree`'d the working directory.

## 9. Open items / unverified assumptions

- Render API fits in 512 MB without the local model (estimated ~200 MB — must measure).
- Indexing speed at ~0.1–0.25 vCPU; guest repo size caps needed.
- Cloudflare Workers AI: batch limit, free-tier card requirement, retrieval parity vs local ONNX (run `retrieval_eval`).
- Whether Upstash supports what the Celery config assumes (moot in hosted mode — no Celery there).
- Groq free-tier rate limits (not researched); Ollama fallback is useless in the hosted deployment.
- Per-user repo quota for logged-in users and daily question caps are tunable defaults, not decided.
- Optional offers pending the owner's approval: add a pointer to this file in CLAUDE.md; add this file to `.gitignore` or commit it.
