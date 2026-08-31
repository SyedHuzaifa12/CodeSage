# CodeSage Backend

FastAPI backend for CodeSage, built as a **Modular Monolith** per the architecture frozen in the root [`CLAUDE.md`](../CLAUDE.md). Through Sprint 0B this is production-grade **infrastructure only** — configuration, logging, DB/cache/vector-store connections, lifespan, middleware, centralized exception handling, health checks, and now the persistence layer (SQLAlchemy models + Alembic migrations). No business logic, business endpoints, or AI code exist yet; those land in later sprints per the build order.

## Running Locally (no Docker)

```bash
pip install -r requirements.txt
cp .env.example .env   # first time only — defaults point at localhost
uvicorn app.main:app --reload
```

PostgreSQL, Redis, and Qdrant must be reachable **and PostgreSQL must have its schema migrated** at startup — the app fails fast otherwise (see [Application Lifespan](#application-lifespan)). The simplest way to satisfy that locally is to run  the data layer via Docker while iterating on the backend directly on the host:

```bash
docker compose up postgres redis qdrant -d   # from the project root
alembic upgrade head                          # from backend/ — creates the tables
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

**Migrations are not run automatically** — the backend will fail to start against a fresh Postgres volume until you apply them once:

```bash
cd backend
alembic upgrade head   # against the Docker-published localhost:5432, via backend/.env
```

This is deliberate: schema changes should be a controlled, explicit step (CLAUDE.md §9 — "never hand-edit tables", and the same discipline extends to never *silently* auto-migrating on container boot either).

| Service | Container | Host port (default) | Data persistence |
|---|---|---|---|
| Backend | `codesage-backend` | `8000` | `repository_storage` volume (cloned repos, at `/app/data/repositories`) |
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

All ports, credentials, and app metadata are driven by the root `.env` file (see `.env.example`) — nothing is hardcoded in `docker-compose.yml` or the Dockerfile.

## Database Models & Migrations

Six SQLAlchemy 2.0 models (`app/models/`), matching CLAUDE.md §9 exactly — **models represent data only**: no  business methods, no CRUD, no service logic.

| Model | Table | Notes |
|---|---|---|
| `Repository` | `repositories` | Owns its own indexing lifecycle: `status` (`pending`/`cloning`/`parsing`/`indexing`/`completed`/`failed`, DB-enforced via `CHECK`), `indexing_progress`, `error_message` — per CLAUDE.md §6, indexing runs as  a `BackgroundTask` with progress tracked here, not in a job queue. |
| `File` | `files` | Belongs to a `Repository`. Unique on `(repository_id, path)`. |
| `Symbol` | `symbols` | Belongs to a `File`. Indexed on `name` and `symbol_type` for metadata search (§8). |
| `Relationship` | `relationships` | An edge in the Knowledge Graph. `source_symbol`/`target_symbol` are **indexed strings, not foreign keys** — the KG spans symbol-, file-, and API/DB-level entities (§8's four logical layers), so a strict FK to `symbols` would make three of the four layers unrepresentable. Scoped by a required `repository_id` FK instead, with composite indexes on `(repository_id, relationship_type)`, `(repository_id, source_symbol)`, and `(repository_id, target_symbol)` for graph expansion. |
| `Report` | `reports` | Belongs to a `Repository`. `report_type` constrained to `summary`/`onboarding`/`architecture`/`impact`. |
| `Conversation` | `conversations` | Belongs to a `Repository`. Persistent chat history only — transient/session state is Redis's job (§7), not this table's. |

Every model gets `id` (UUID, Python-generated), `created_at`/`updated_at` (DB-generated via `TimestampMixin` in `app/models/base.py`), and cascades: deleting a `Repository` row cascades to every child table (`ON DELETE CASCADE`), matching `DELETE /repositories/{id}`'s documented behavior of removing the entire local index (§9). No soft delete — CLAUDE.md doesn't define one, and the delete semantics it does define ("removes... metadata, vectors, cached data") describe a real delete, not a flag.

### Migration commands

```bash
cd backend

# create a new migration after changing a model
alembic revision --autogenerate -m "describe the change"

# apply all pending migrations
alembic upgrade head

# roll back one migration
alembic downgrade -1

# check current DB revision / migration history
alembic current
alembic history
```

### Migration workflow

1. Add/change a model in `app/models/`.
2. If it's a new model, import it in `app/models/__init__.py` (Alembic's autogenerate and the startup schema check both rely on every model being imported so it registers with `Base.metadata`).
3. `alembic revision --autogenerate -m "..."` — review the generated file in  `app/db/migrations/versions/` before applying; autogenerate is a diff tool, not a guarantee.
4. `alembic upgrade head` against your  target database.
5. Restart the backend — the lifespan schema check re-verifies every expected table exists.

Migrations are **never** run automatically by the application or the Docker image — see the note in [Running with Docker](#running-with-docker).

## Configuration

All configuration is loaded via `pydantic-settings` in `app/core/config.py`,  split into six independently-validated groups, each reading from environment variables (and, locally, `.env`):

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

- **Startup**: verifies PostgreSQL is reachable (`SELECT 1`), **then verifies every model-defined table actually exists** (schema introspection against `Base.metadata`, no `CREATE TABLE` — that only ever happens through Alembic), then verifies Redis and Qdrant are reachable (`PING`, `get_collections()`). If any check fails, the app raises immediately and refuses to start — a broken or unmigrated dependency should be loud, not silent.
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
├── db/                 # Postgres / Qdrant / Redis client setup + migrations/ (Alembic env + versions/)
├── models/              # SQLAlchemy models: Repository, File, Symbol, Relationship, Report, Conversation
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

As of Sprint 1A, `repository/` (clone/CRUD/status lifecycle) is implemented. Still not present: file parsing or Tree-sitter (`ingestion/`), chunking/embeddings/Knowledge Graph (`knowledge/`), retrieval, the AI pipeline, reports, and authentication/authorization. These are added module-by-module in later sprints, each validated through the Streamlit DevTools console before being wired into the production frontend.
