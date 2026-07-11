# CodeSage Backend

FastAPI backend for CodeSage, built as a **Modular Monolith** per the architecture frozen in the root [`CLAUDE.md`](../CLAUDE.md). This is the Sprint 0.1 project skeleton — folder structure and boilerplate only. No business logic, endpoints, database models, or AI code exist yet; those land in later sprints per the build order in `CLAUDE.md` §21.

## Running

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Starts the FastAPI app with no registered routes yet (Swagger UI at `/docs` will be empty until the API layer is implemented).

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

By design, this skeleton does not include: API endpoints, database models/migrations, DB connection logic, AI/LLM code, or business logic of any kind. These are added module-by-module in later sprints, each validated through the Streamlit DevTools console before being wired into the production frontend.
