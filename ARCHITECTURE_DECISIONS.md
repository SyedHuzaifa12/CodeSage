# Architecture Decision Records — CodeSage

This document records the significant architectural decisions made for the CodeSage platform. It exists so that every design choice has a traceable **context → decision → rationale → trade-off**, instead of living only in institutional memory.

These ADRs are binding for Version 1. They are the canonical source of truth alongside `CLAUDE.md`; where the `docs/` volumes disagree with an ADR here, the ADR wins.

**Adding a new ADR:** append it at the end with the next sequential number, status `Proposed` until the user approves it, then `Accepted`. Never edit the *Decision* or *Rationale* of an existing accepted ADR — if a decision changes, write a new ADR that supersedes it and mark the old one `Superseded by ADR-XXX`. Do not do this unilaterally — architecture changes follow the Architecture-First Policy in `CLAUDE.md`.

## Index

| ADR | Title |
|---|---|
| [001](#adr-001--modular-monolith-architecture) | Modular Monolith Architecture |
| [002](#adr-002--backend-first-development-strategy) | Backend-First Development Strategy |
| [003](#adr-003--hybrid-rag-retrieval-strategy) | Hybrid RAG Retrieval Strategy |
| [004](#adr-004--lightweight-knowledge-graph-in-postgresql-instead-of-neo4j) | Lightweight Knowledge Graph in PostgreSQL (instead of Neo4j) |
| [005](#adr-005--fastapi-as-the-backend-framework) | FastAPI as the Backend Framework |
| [006](#adr-006--postgresql--qdrant--redis-as-the-only-data-stores) | PostgreSQL + Qdrant + Redis as the Only Data Stores |
| [007](#adr-007--tree-sitter-for-source-code-parsing) | Tree-sitter for Source Code Parsing |
| [008](#adr-008--langgraph-linear-workflow-instead-of-multi-agent) | LangGraph Linear Workflow (instead of Multi-Agent) |
| [009](#adr-009--streamlit-developer-console-for-backend-first-validation) | Streamlit Developer Console for Backend-First Validation |
| [010](#adr-010--nextjs-as-the-production-frontend) | Next.js as the Production Frontend |
| [011](#adr-011--fastapi-backgroundtasks-instead-of-celery) | FastAPI BackgroundTasks instead of Celery |
| [012](#adr-012--local-first-repository-processing) | Local-First Repository Processing |
| [013](#adr-013--ai-module-isolation-from-databases) | AI Module Isolation from Databases |
| [014](#adr-014--groq-primary-with-ollama-local-fallback-for-llm-inference) | Groq Primary with Ollama Local Fallback for LLM Inference |
| [015](#adr-015--technology-stack-freeze) | Technology Stack Freeze |
| [016](#adr-016--version-1-scope-freeze) | Version 1 Scope Freeze |

---

## ADR-001 — Modular Monolith Architecture

**Status:** Accepted

**Context**
CodeSage is built and maintained by a single engineer, on a consumer-grade laptop, at zero budget. It must remain easy to develop, debug, and deploy while still resembling a production system that could scale later. A microservices split was considered given the number of distinct responsibilities (repository management, ingestion, knowledge, retrieval, AI, reports).

**Decision**
Build CodeSage as a single deployable FastAPI application (a **Modular Monolith**), internally divided into clearly bounded modules (`repository/`, `ingestion/`, `knowledge/`, `retrieval/`, `ai/`, `reports/`, `system/`), each with enforced one-way dependencies and no circular calls between modules.

**Rationale**
- One developer and one deployment target make microservices' operational overhead (service discovery, inter-service auth, distributed tracing, network failure handling) pure cost with no corresponding benefit.
- A modular monolith still enforces separation of concerns via module boundaries, so it does not sacrifice maintainability.
- Debugging, local development, and demoing (`docker compose up`) are dramatically simpler with one process.

**Consequences / Trade-offs**
- (+) Fast local iteration, simple deployment, easy for a solo engineer to reason about the whole system.
- (+) Any module can be extracted into its own service later without a rewrite, because module boundaries are already enforced.
- (–) No independent scaling of hot modules (e.g., embeddings vs. API) within V1 — the whole app scales as one unit.
- (–) Requires discipline to avoid modules quietly reaching into each other's internals; enforced via code review against `CLAUDE.md` module rules.

---

## ADR-002 — Backend-First Development Strategy

**Status:** Accepted

**Context**
AI reasoning quality, retrieval quality, and Knowledge Graph correctness are the actual product. A polished frontend built against an unstable or unvalidated backend would create rework and mask integration bugs behind UI polish.

**Decision**
Build and validate the entire backend and AI pipeline first, using an internal Streamlit Developer Console (see ADR-009) as the only client, before writing any Next.js frontend code. The production frontend consumes the same APIs the console already validated.

**Rationale**
- Intelligence is the product; presentation is secondary and swappable.
- Backend APIs stabilize before any UI framework decisions or component work begins, avoiding churn in the frontend from a moving backend contract.
- Matches the project's sprint plan (Sprints 0–6 are backend/AI; Sprint 7 is frontend only after Sprint 6 passes).

**Consequences / Trade-offs**
- (+) Frontend work never blocks on backend design changes.
- (+) Every API is manually exercised and debugged before a UI depends on it.
- (–) No visual/demo-able product exists until later sprints — acceptable given the target audience (technical reviewers/recruiters) values engineering substance over early visuals.

---

## ADR-003 — Hybrid RAG Retrieval Strategy

**Status:** Accepted

**Context**
Pure vector similarity search retrieves semantically similar text but misses structural relationships in code (e.g., asking "how does login work" needs `middleware.py` and `database.py`, not just files containing the word "login"). Repository questions require both meaning-based and relationship-based retrieval.

**Decision**
Retrieval combines exactly four techniques, in this order: **Semantic Search** (Qdrant vector similarity) → **Metadata Search** (PostgreSQL filenames/symbols/APIs) → **Knowledge Graph Expansion** (relationship traversal from initial hits) → **Hybrid Context Ranking** (merge and score by semantic similarity + graph distance + symbol relevance + file importance). No additional retrieval technique (BM25, full-text/Elasticsearch, etc.) is introduced in V1.

**Rationale**
- Embeddings alone cannot represent relationships like `calls`, `imports`, `depends_on` — these require graph traversal.
- Metadata search catches exact symbol/API/filename matches that semantic search can miss or under-rank.
- Ranking multiple signals together produces more complete, better-grounded context for the reasoning stage than any single technique alone.

**Consequences / Trade-offs**
- (+) Retrieval quality is materially better than vector-only RAG for codebase questions — the project's core differentiator.
- (+) Bounded technique set keeps the retrieval module simple to test and reason about in isolation from the LLM.
- (–) More moving parts than a single vector search call — each source must be built, tested, and ranked independently.
- (–) Retrieval latency is the sum of several lookups rather than one; must be monitored against the <3s query target.

---

## ADR-004 — Lightweight Knowledge Graph in PostgreSQL (instead of Neo4j)

**Status:** Accepted

**Context**
The platform needs to represent and traverse relationships between code entities (calls, imports, dependencies, symbol relationships) to power Knowledge Graph Expansion (ADR-003). A dedicated graph database (Neo4j) is the conventional choice for this kind of workload.

**Decision**
Implement the Knowledge Graph as a single relational table (`relationships: source_symbol, target_symbol, relationship_type`) inside the existing PostgreSQL instance. The four conceptual layers — Call Graph, Import Graph, Dependency Graph, Symbol Relationships — are logical groupings distinguished by `relationship_type`, not separate tables or a separate database.

**Rationale**
- Repository-scale graphs here are shallow, bounded-degree traversals (a handful of hops from a retrieved symbol), well within what recursive SQL/adjacency queries on an indexed table can do efficiently.
- Avoids a fourth piece of infrastructure, a new query language, and a new operational surface (backup, monitoring, deployment) for a workload that doesn't need it.
- Keeps the "only three databases" principle (ADR-006) intact and the stack demonstrable via one `docker compose up`.

**Consequences / Trade-offs**
- (+) Zero additional infrastructure; one less thing to run, monitor, and explain in deployment.
- (+) Relationship data joins naturally with existing metadata (files, symbols) in the same transactional store.
- (–) Deep or highly connected graph traversals (many hops, complex pattern matching) would be slower and more awkward in SQL than in Cypher — acceptable for V1's shallow-expansion use case, but the first constraint to revisit if V2 needs deeper graph reasoning.
- (–) No built-in graph visualization tooling — the Streamlit Knowledge Graph Explorer must build this itself from the relational data.

---

## ADR-005 — FastAPI as the Backend Framework

**Status:** Accepted

**Context**
The backend needs to support synchronous CRUD-style endpoints, long-running background indexing, and streaming chat responses, while integrating cleanly with the Python-native AI/ML ecosystem (Tree-sitter bindings, embedding models, LangGraph).

**Decision**
Use FastAPI as the sole backend web framework.

**Rationale**
- Native `async`/`await` support suits I/O-bound work (DB calls, LLM calls, streaming) without extra concurrency frameworks.
- First-class support for streaming responses, needed for `/chat/stream`.
- Automatic OpenAPI/Swagger generation satisfies the API documentation requirement (`CLAUDE.md` §10, §18) with no extra tooling.
- Built-in dependency injection (`Depends`) supports clean, testable service wiring (`CLAUDE.md` §11).
- Strong ecosystem fit with Python AI tooling (LangGraph, embedding libraries, Tree-sitter Python bindings).

**Consequences / Trade-offs**
- (+) Async-first design maps directly onto the platform's I/O-heavy workload.
- (+) Self-documenting API reduces documentation maintenance burden.
- (–) Requires discipline around blocking calls (e.g., CPU-bound parsing) so they don't stall the event loop — mitigated by running such work in background tasks (ADR-011).

---

## ADR-006 — PostgreSQL + Qdrant + Redis as the Only Data Stores

**Status:** Accepted

**Context**
The platform needs relational metadata storage, vector similarity search, and a caching layer. It would be easy to over-provision (e.g., a separate graph DB, a separate document store, a search engine) given the range of features (chat, graph, reports, search).

**Decision**
Limit persistent/cache infrastructure to exactly three systems:
- **PostgreSQL** — structured metadata, the lightweight Knowledge Graph, reports, conversation history, indexing status.
- **Qdrant** — vector embeddings (single collection: `repository_chunks`).
- **Redis** — cache and transient session state only; never durable, never a task queue broker.

**Rationale**
- Each store has one clear job; there is no overlapping responsibility to reconcile.
- Matches the zero-budget, self-hosted-via-Docker-Compose constraint — three well-understood, free, open-source systems are demonstrable in minutes.
- Reduces operational surface area for a solo engineer to reason about, back up, and debug.

**Consequences / Trade-offs**
- (+) Simple mental model: "if it's a relationship or fact, it's Postgres; if it's a vector, it's Qdrant; if it's ephemeral, it's Redis."
- (+) Entire data layer is provisioned by one `docker-compose.yml`.
- (–) No dedicated search engine means metadata/keyword search relies on PostgreSQL's native indexing (trigram/full-text indexes) rather than a purpose-built engine — sufficient at V1 repository scale, a candidate to revisit if corpus size grows substantially.

---

## ADR-007 — Tree-sitter for Source Code Parsing

**Status:** Accepted

**Context**
Extracting functions, classes, imports, and symbols from arbitrary source files could be done with regular expressions/heuristics or with a real parser producing an Abstract Syntax Tree.

**Decision**
Use Tree-sitter for all source code parsing and symbol/AST extraction, across all supported languages.

**Rationale**
- AST-based extraction is structurally accurate; regex-based extraction is brittle and breaks on valid-but-unusual syntax.
- Tree-sitter supports incremental parsing and a consistent query interface across many languages, which fits the multi-language nature of real repositories.
- Reliable symbol extraction is a prerequisite for a trustworthy Knowledge Graph (ADR-004) — errors here propagate into every downstream retrieval and reasoning step.

**Consequences / Trade-offs**
- (+) Significantly more reliable symbol/relationship extraction than pattern matching.
- (+) Extending to a new language is a matter of adding a grammar, not rewriting extraction logic (`CLAUDE.md` extensibility goal).
- (–) Requires maintaining per-language grammars and query files; unsupported/exotic languages fall back to being ignored rather than partially parsed.

---

## ADR-008 — LangGraph Linear Workflow (instead of Multi-Agent)

**Status:** Accepted

**Context**
The AI pipeline (intent → retrieval → context → reasoning → verification → format) needs deterministic, debuggable orchestration. A more elaborate multi-agent design (planner agents, autonomous agent-to-agent delegation, dynamic branching) was considered given the "AI Engine" framing of the product.

**Decision**
Orchestrate the AI pipeline as a single **linear LangGraph** with fixed stage order: `Intent → Retrieve → Build Context → Reason → Verify → Format → End`. No planner agents, no autonomous multi-agent collaboration, no dynamic branching in V1.

**Rationale**
- A fixed pipeline is fully predictable, easy to test stage-by-stage, and easy to explain — all stated project priorities.
- Multi-agent systems introduce non-determinism, harder debugging, and higher LLM cost/latency for a V1 whose actual bottleneck is retrieval quality, not orchestration flexibility.
- LangGraph still provides the workflow/state-management scaffolding needed, without requiring agent autonomy.

**Consequences / Trade-offs**
- (+) Deterministic execution order makes failures easy to localize to a single stage.
- (+) Each stage is independently unit-testable (`CLAUDE.md` §16).
- (–) No dynamic re-planning if a stage's output is insufficient (e.g., retrieval returns nothing) — handled instead by explicit failure propagation ("if retrieval fails, stop; don't call the LLM") rather than agentic retry/re-planning. Revisit only if V2 requirements demand it.

---

## ADR-009 — Streamlit Developer Console for Backend-First Validation

**Status:** Accepted

**Context**
Backend-first development (ADR-002) requires *some* client to exercise APIs, inspect retrieval/graph output, and debug the AI pipeline, before the production frontend exists.

**Decision**
Build a Streamlit application (`devtools/`) as an internal-only developer console: repository import/status, indexing progress, an AI chat playground with visible retrieved context/prompt/confidence, a Knowledge Graph explorer, and system health monitoring. It is never shipped as the product and is not a Version 1 user-facing deliverable.

**Rationale**
- Streamlit lets a solo engineer build a functional internal tool in a fraction of the time a React app would take, with no separate build/deploy pipeline.
- Direct visibility into retrieved chunks, graph expansion, and final prompts is essential for debugging hallucinations and retrieval gaps — a plain API client wouldn't surface this.
- Keeps frontend framework decisions (ADR-010) fully decoupled from backend/AI iteration speed.

**Consequences / Trade-offs**
- (+) Immediate feedback loop for every new backend/AI feature.
- (+) Zero impact on production frontend timeline or design.
- (–) Two client codebases exist during development (console + eventual frontend) — acceptable since the console is disposable tooling, not a maintained product surface.

---

## ADR-010 — Next.js as the Production Frontend

**Status:** Accepted

**Context**
Version 1 requires a production-facing UI (dashboard, chat, reports) once the backend is stable (post Sprint 6), suitable for demoing to recruiters/technical reviewers and usable as a real product surface.

**Decision**
Use Next.js (React + TypeScript) as the sole production frontend framework, built only after backend/AI validation is complete via the Streamlit console.

**Rationale**
- Next.js is the modern, widely-adopted standard for production React applications, with strong support for streaming UI (needed for `/chat/stream`) and SSR/SEO if ever relevant.
- Building it last avoids rework: the API contract is already proven stable by the time frontend work starts.
- TypeScript strengthens the contract between frontend and the documented API envelope (`CLAUDE.md` §10).

**Consequences / Trade-offs**
- (+) Frontend work proceeds against a frozen, validated API surface — minimal churn.
- (+) Familiar, well-supported framework or a portfolio audience to evaluate.
- (–) No user-facing product exists until Sprint 7 — an accepted trade-off of the backend-first strategy (ADR-002).

---

## ADR-011 — FastAPI BackgroundTasks instead of Celery

**Status:** Accepted

**Context**
Repository indexing (clone, parse, chunk, embed, graph-build) is a long-running operation that must not block the request/response cycle, and should be resumable/retryable per the platform's reliability requirements. Celery + a broker (Redis/RabbitMQ) is the conventional solution for background job processing in Python web apps.

**Decision**
Use FastAPI's built-in `BackgroundTasks` (or equivalent in-process async execution) for repository indexing, with progress and status tracked in a PostgreSQL status table on `repositories`. Do not introduce Celery or any distributed task queue in V1.

**Rationale**
- A single-process modular monolith (ADR-001) does not yet have multiple workers to distribute work across — a distributed queue would add operational complexity (broker management, worker processes, monitoring) without a corresponding scaling need.
- Redis is deliberately scoped to cache/session-state only (ADR-006); introducing it as a Celery broker would blur that boundary.
- Indexing status/resumability needs are met by a status column/table plus retry logic in the indexing service, without requiring a full task-queue system.

**Consequences / Trade-offs**
- (+) No new infrastructure component; fits the zero-cost, Docker-Compose-in-minutes constraint.
- (+) Simpler failure model: one process, one place to look when indexing fails.
- (–) No horizontal scaling of indexing workers within V1 — all indexing runs in the same process as the API server. This is the explicit first candidate to revisit (Celery or an equivalent queue) if/when the platform needs to scale indexing throughput independently of API traffic.

---

## ADR-012 — Local-First Repository Processing

**Status:** Accepted

**Context**
Organizations and individual developers are increasingly sensitive about source code leaving their environment. The platform's target users include enterprises and privacy-conscious open-source maintainers.

**Decision**
By default, all repository data — source files, embeddings, Knowledge Graph, cached context — stays on local/self-hosted storage. No repository content is uploaded to a third-party cloud service unless a future, explicitly opted-in configuration enables it. The only outbound network calls in the reasoning pipeline are to the configured LLM provider (Groq) with structured context, not raw source dumps, and Ollama is available for a fully offline path.

**Rationale**
- Privacy is a stated product principle ("Local First") and a real adoption blocker for the target market if violated by default.
- Zero-budget constraint reinforces this: local/self-hosted infrastructure is also the cheapest infrastructure.
- Reduces security surface — there is no repository data at rest on any third-party server to protect or leak.

**Consequences / Trade-offs**
- (+) Removes an entire class of data-exfiltration and compliance concerns by default.
- (+) Fully demoable offline (Ollama path) with no external dependency.
- (–) Local-only processing bounds V1 to single-machine compute — large repositories are constrained by local RAM/CPU rather than elastic cloud scaling. Acceptable given the 16GB-RAM consumer-laptop target.

---

## ADR-013 — AI Module Isolation from Databases

**Status:** Accepted

**Context**
Without an enforced boundary, it would be easy for AI pipeline code to reach directly into Qdrant/PostgreSQL for "just one more piece of context," eroding the separation between reasoning and data access and making the AI module untestable in isolation.

**Decision**
The `ai/` module never accesses PostgreSQL, Qdrant, or Redis directly, and has no `repository.py`. All repository context flows through: `AI Engine → Retrieval Module → Knowledge Module → Databases`. The Knowledge module is the only module with direct storage access for embeddings/graph data; Retrieval orchestrates search and ranking on top of it.

**Rationale**
- Keeps the AI module's responsibility strictly to reasoning: intent, prompting, verification, formatting — not data access.
- Makes the AI pipeline independently testable with mocked/stubbed retrieval results, rather than requiring live databases for every AI unit test.
- Enforces a single, auditable path by which repository evidence reaches the LLM, which is central to the platform's grounding/anti-hallucination guarantees.

**Consequences / Trade-offs**
- (+) Clear, enforceable module boundary; a code review checklist item, not a convention that can silently drift.
- (+) Retrieval and Knowledge can evolve (e.g., swap Qdrant for another vector store) without touching AI code.
- (–) Adds one layer of indirection for every piece of context the AI module needs — an intentional cost in exchange for testability and boundary integrity.

---

## ADR-014 — Groq Primary with Ollama Local Fallback for LLM Inference

**Status:** Accepted

**Context**
The reasoning stage (ADR-008) needs an LLM. The platform must remain usable at zero cost and must not have a hard dependency on any single external provider, per the project's LLM-independence goal, while still being fast enough to hit the <3s query / <1s first-token targets.

**Decision**
Use Groq's free-tier hosted inference as the primary LLM provider for the Reasoning Engine, with Ollama-hosted local models as an offline/fallback path. No other providers (OpenAI, Anthropic, Gemini, DeepSeek) are integrated in V1, narrowing the broader multi-provider ambition in earlier planning documents to this concrete pair for now.

**Rationale**
- Groq's free tier offers very low latency inference, directly serving the platform's streaming/response-time targets.
- Ollama provides a genuine zero-dependency, fully offline path, reinforcing the local-first principle (ADR-012) and providing resilience if the hosted provider is unavailable.
- Narrowing to two providers avoids building and maintaining a generalized adapter layer for providers that aren't actually used yet — that abstraction can be built when a third provider is genuinely needed.

**Consequences / Trade-offs**
- (+) Meets performance targets at zero cost.
- (+) Graceful degradation to fully offline operation if the hosted provider is unreachable.
- (–) LLM output quality/behavior is bounded by what Groq's hosted models and locally-runnable Ollama models can do — larger frontier models (GPT-4/Claude-class) are not available in V1. Revisit if reasoning quality proves insufficient for a given feature.

---

## ADR-015 — Technology Stack Freeze

**Status:** Accepted

**Context**
A solo-engineer, portfolio-oriented project is vulnerable to continuous re-evaluation of tooling ("should I try X instead?"), which delays delivery without improving the end product. The stack chosen (ADR-005 through ADR-007, ADR-014, plus Next.js, Streamlit, Docker Compose, Alembic) already satisfies every stated technical constraint (free/open-source, container-friendly, Python-ecosystem-friendly, replaceable via interfaces).

**Decision**
Freeze the technology stack for Version 1 exactly as follows: Next.js (frontend), Streamlit (developer console), FastAPI (backend), PostgreSQL, Qdrant, Redis (data layer), Tree-sitter (parsing), BAAI/bge-small-en-v1.5 (embeddings), LangGraph (orchestration), Groq + Ollama (LLM), Docker Compose (deployment). No new framework, database, or provider is introduced without explicit user approval, per the Architecture-First Policy.

**Rationale**
- Every technology in the frozen stack was selected against explicit criteria (open-source, production-adopted, free-tier viable, Python-ecosystem fit, replaceable through interfaces) — there is no unmet technical need driving a change.
- Feature creep in tooling is functionally identical to feature creep in scope: both consume time without shipping value.
- A frozen stack is also a clearer, more defensible story in a portfolio/interview context than a stack that changed every few weeks.

**Consequences / Trade-offs**
- (+) Eliminates an entire category of mid-project rework and decision fatigue.
- (+) Every module is built behind interfaces (ADR-004, ADR-006 rationale) so a future, deliberate swap remains possible without a rewrite.
- (–) Known limitations of chosen tools (e.g., SQL-based graph traversal depth, Groq/Ollama model ceiling) are accepted for V1 rather than solved by swapping tools — they are documented here as explicit, revisitable trade-offs rather than silently worked around.

---

## ADR-016 — Version 1 Scope Freeze

**Status:** Accepted

**Context**
The product roadmap spans three versions (Repository Intelligence → Engineering Intelligence → Autonomous Engineering Intelligence). Without a hard scope boundary, V2/V3 capabilities (PR impact analysis, technical debt detection, health scoring, multi-repo reasoning, AI design review) are tempting to pull forward mid-build, which historically causes incomplete, unshippable V1s.

**Decision**
Version 1 includes exactly: Repository Intelligence, Hybrid RAG, Lightweight Knowledge Graph, Repository Chat, Onboarding Documentation, Architecture Generation, Impact Analysis (single-PR/diff level, not the full V2 analytics suite), Developer Console, and the Production Frontend. Explicitly excluded from V1: multi-agent systems, Neo4j, Celery, microservices, PR review automation, code generation/editing, technical debt detection, enterprise features, and any other V2/V3 functionality.

**Rationale**
- A complete, polished V1 demonstrates more engineering maturity than a partially-built superset of V1+V2 features.
- Every excluded item has a clear architectural reason documented elsewhere in this file (ADR-001, ADR-004, ADR-008, ADR-011) — the exclusions are principled, not arbitrary.
- Matches the sprint-based delivery plan (Sprint 0–8); scope creep directly threatens the "each sprint ends in a stable, working increment" rule.

**Consequences / Trade-offs**
- (+) Forces every design decision toward simplicity and shippability, reinforcing all prior ADRs in this document.
- (+) Gives future versions (V2/V3) a stable, proven foundation to extend rather than an unfinished one to rescue.
- (–) Genuinely useful V2 capabilities (e.g., technical debt detection) are deferred even where a user might want them sooner — any request to pull one forward must go through the Architecture-First Policy conflict process in `CLAUDE.md`, not be added silently.
