# CodeSage Backend

FastAPI backend for CodeSage, built as a **Modular Monolith** per the architecture frozen in the root [`CLAUDE.md`](../CLAUDE.md). Through Sprint 0A this is production-grade **infrastructure only** — configuration, logging, DB/cache/vector-store connections, lifespan, middleware, centralized exception handling, and health checks. No business logic, business endpoints, database models/tables, or AI code exist yet; those land in later sprints per the build order in `CLAUDE.md` §21.

## Running Locally (no Docker)

```bash
pip install -r requirements.txt
cp .env.example .env   # first time only — defaults point at localhost
uvicorn app.main:app --reload
```

PostgreSQL, Redis, and Qdrant must be reachable at startup — the app fails fast if any of them can't be reached (see [Application Lifespan](#application-lifespan)). The simplest way to satisfy that locally is to run the data layer via Docker while iterating on the backend directly on the host:

```bash
docker compose up postgres redis qdrant -d   # from the project root
```

Swagger UI at `/docs` now shows the three health endpoints; no business routes exist yet.

## Running with Docker

The full local stack (PostgreSQL, Redis, Qdrant, backend) is defined in the root [`docker-compose.yml`](../docker-compose.yml).

```bash
# from the project root
cp .env.example .env      # first time only
docker compose up --build
```

This builds the backend image from `backend/Dockerfile` and starts all four services on a shared `codesage-network` bridge network, so the backend reaches the data layer by service name (`postgres`, `redis`, `qdrant`) rather than `localhost`. Each service has a healthcheck, and the backend only starts once Postgres, Redis, and Qdrant report healthy (`depends_on: condition: service_healthy`).

| Service | Container | Host port (default) | Data persistence |
|---|---|---|---|
| Backend | `codesage-backend` | `8000` | — (stateless) |
| PostgreSQL | `codesage-postgres` | `5432` | `postgres_data` volume |
| Redis | `codesage-redis` | `6379` | `redis_data` volume (AOF enabled) |
| Qdrant | `codesage-qdrant` | `6333` (HTTP), `6334` (gRPC) | `qdrant_data` volume |

Verify everything is up:

```bash
docker compose ps                        # all four services should show "healthy"
curl http://localhost:8000/health/live   # {"success": true, ...}
curl http://localhost:8000/health/ready  # {"success": true, "data": {"ready": true, ...}}
curl http://localhost:8000/health        # full status incl. per-dependency health
```

Stop and remove containers (data volumes persist across restarts):

```bash
docker compose down
```

Wipe all persisted data (Postgres/Redis/Qdrant volumes) as well:

```bash
docker compose down -v
```

All ports, credentials, and app metadata are driven by the root `.env` file (see `.env.example`) — nothing is hardcoded in `docker-compose.yml` or the Dockerfile. Database *tables* and *migrations* are still not part of this sprint (see [What's Not Here Yet](#whats-not-here-yet)) — the backend connects to Postgres/Redis/Qdrant, but nothing is persisted yet.

## Configuration

All configuration is loaded via `pydantic-settings` in `app/core/config.py`, split into six independently-validated groups, each reading from environment variables (and, locally, `.env`):

| Class | Concern | Key env vars |
|---|---|---|
| `AppSettings` | App metadata, CORS, trusted hosts | `APP_NAME`, `ENVIRONMENT`, `DEBUG`, `CORS_ORIGINS`, `ALLOWED_HOSTS` |
| `DatabaseSettings` | PostgreSQL | `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |
| `RedisSettings` | Redis | `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_PASSWORD` |
| `QdrantSettings` | Qdrant | `QDRANT_HOST`, `QDRANT_HTTP_PORT`, `QDRANT_GRPC_PORT` |
| `LLMSettings` | Groq/Ollama config (unused until the AI module lands) | `LLM_PROVIDER`, `GROQ_API_KEY`, `GROQ_MODEL`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `EMBEDDING_MODEL` |
| `LoggingSettings` | Logging behaviour | `LOG_LEVEL`, `LOG_FORMAT`, `LOG_TO_CONSOLE`, `LOG_TO_FILE`, `LOG_DIR` |

Access via `app.core.config.get_settings()` (cached, so it's constructed once per process): `settings.database.postgres_host`, `settings.llm.groq_model`, etc. Secrets (`POSTGRES_PASSWORD`, `GROQ_API_KEY`, `REDIS_PASSWORD`) are typed as `SecretStr` so they never appear in `repr()`/logs by accident.

## Logging

`app/core/logging.py` configures the root logger once at import time (`configure_logging()`), with:

- **Console** handler (stdout) and **rotating file** handler (`logs/codesage.log`, 10 MB × 5 backups), each independently toggleable via `LOG_TO_CONSOLE` / `LOG_TO_FILE`.
- **Structured JSON** log lines by default (`LOG_FORMAT=json`): `{"timestamp", "level", "logger", "message", "request_id"}`, or a human-readable text format for local reading.
- **Environment-aware level**: `LOG_LEVEL` wins if set; otherwise `DEBUG` in development, `INFO` elsewhere.
- **Request ID correlation**: `RequestIDMiddleware` binds a per-request ID into a `contextvars.ContextVar`; a logging filter injects it into every log record automatically — no need to pass it through call signatures.

No `print()` statements anywhere — use `logging.getLogger(__name__)` (or the `get_logger()` dependency) everywhere.

## Application Lifespan

`app/core/lifespan.py` runs on every app start/stop:

- **Startup**: verifies PostgreSQL, Redis, and Qdrant are all reachable (`SELECT 1`, `PING`, `get_collections()` respectively). If any check fails, the app raises immediately and refuses to start — a broken dependency should be loud, not silent.
- **Shutdown**: disposes the SQLAlchemy engine's pool and closes the Redis/Qdrant clients cleanly.

## Health Endpoints

Three endpoints, deliberately mounted **unversioned** (`app/api/health.py`, not under `/api/v1`) since infrastructure probes (Docker `HEALTHCHECK`, load balancers, k8s) need a stable path independent of API versioning:

| Endpoint | Purpose | Checks dependencies? |
|---|---|---|
| `GET /health` | Full application status: metadata, uptime, per-dependency health | Yes |
| `GET /health/live` | Is the process alive? (liveness) | No — cheap, no I/O |
| `GET /health/ready` | Can it serve traffic right now? (readiness) | Yes — Postgres, Redis, Qdrant |

All three return the standard envelope (`success` / `message` / `data`) and a `503` if a checked dependency is down.

## Middleware & Exception Handling

`app/middleware/` registers, outermost-to-innermost: **Request ID** → **Trusted Host** → **CORS** → **GZip** (no auth middleware yet — that's a later sprint). `app/exceptions/handlers.py` centralizes three handlers — validation errors (422), `HTTPException` (its own status code), and any unhandled exception (500, logged in full, never exposed) — all returning the same `{success, message, errors}` envelope from CLAUDE.md §10.

## Module Layout

```
app/
├── main.py            # FastAPI entry point
├── core/               # config, logging, security, constants, lifespan — shared app infra
├── db/                 # Postgres / Qdrant / Redis client setup + Alembic migrations
├── models/              # SQLAlchemy models (populated when each module's schema lands)
├── schemas/             # shared, module-agnostic Pydantic DTOs
├── api/v1/              # versioned route registration (routes only, no business logic)
│
├── repository/          # clone, CRUD, metadata, status — never parses code
├── ingestion/            # file walk, Tree-sitter parsing, symbol/import extraction — never embeds
├── knowledge/            # chunking, embeddings, Knowledge Graph — owns all storage access
├── retrieval/             # hybrid search orchestration, ranking, context building — via knowledge/, never the DB directly
├── ai/                    # intent → retrieval → context → reasoning → verification → format pipeline
├── reports/               # onboarding, architecture, summary, impact document generation
│
├── services/             # shared cross-module business services
├── middleware/            # request ID, CORS, rate limiting, logging middleware
├── utils/                 # pure, generic helper functions
├── exceptions/             # shared base exceptions + centralized exception handlers
├── shared/{types,interfaces,constants,helpers}/  # cross-cutting shared code
└── tests/                  # unit + integration tests
```

Every module above **except `ai/`** follows the same internal pattern:

```
module_name/
├── api.py          # route handlers
├── service.py      # business logic
├── repository.py   # database access
├── schemas.py      # request/response DTOs
├── exceptions.py   # module-specific exceptions
└── utils.py        # module-local helpers
```

`ai/` intentionally follows its own structure (pipeline `engine/` + `prompts/`, `graph/`, `embeddings/`, `llm/`, `memory/`, `tools/`, `services/`, `schemas/`, `exceptions/`, `utils/`) because it never owns a database access layer — it always reaches repository context through `retrieval/` → `knowledge/`. See `CLAUDE.md` §7 for the full rationale.

## Module Responsibility Boundaries

- `repository/` never parses code.
- `ingestion/` never generates embeddings.
- `knowledge/` never answers user questions; it is the **only** module with direct DB/vector-store access.
- `retrieval/` never calls the LLM and never queries a database directly — it goes through `knowledge/`.
- `ai/` never queries any database directly — it goes through `retrieval/`.
- `reports/` only reads from `ai/` and `knowledge/` output; it does not perform retrieval itself.

## What's Not Here Yet

By design, this sprint does not include: business API endpoints, database models/tables, Alembic migrations, authentication/authorization, or AI/LLM code. These are added module-by-module in later sprints, each validated through the Streamlit DevTools console before being wired into the production frontend.
