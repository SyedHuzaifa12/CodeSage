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

---

## ADR-017 — Hybrid Retrieval Fusion (Sprint 4)

**Status:** Accepted

**Context**
CodeSage's differentiator (per the Sprint 4 brief) is that retrieval must combine structural repository intelligence with semantic search, not behave as a generic single-source vector RAG pipeline. Three genuinely different retrieval sources now exist: Qdrant semantic search (Sprint 3), PostgreSQL symbol/file metadata (Sprints 2A/2B), and the relationship graph (Sprint 2B). A decision was needed on how their results combine into one ranked, explainable result set.

**Decision**
Fuse candidates via a deterministic, configurable linear scoring formula — `final = w_semantic·semantic + w_lexical·lexical + w_structural·structural + entry_point_boost? + hotspot_boost?` — computed in `app/retrieval/candidates.py::fuse_and_rank`. Weights live in `RetrievalSettings` (config, not code). Deduplication merges same-evidence candidates (by chunk id, then symbol id, then file id) before scoring, unioning their per-source scores rather than picking one source arbitrarily. Structural expansion is capped to one relationship hop from a semantic/lexical seed. Lexical search runs over `pg_trgm` trigram similarity on symbol/file names — not raw source text, which isn't persisted in Postgres by design (Sprint 3).

**Rationale**
- A linear, named-component formula is explainable and testable by construction — every result's score can be decomposed and audited, unlike a learned/black-box ranker (§6 of the Sprint 4 brief explicitly disallows inventing arbitrary ML scores).
- Config-driven weights allow tuning retrieval quality without a code change or redeploy of scoring logic, and make future reranking (Sprint 5+) an additive change, not a rewrite.
- One-hop-only structural expansion avoids unbounded graph traversal (explicitly out of scope) while still surfacing the single most valuable class of structural context (direct callers/callees/implementers/dependents).
- Reusing `pg_trgm` (a built-in PostgreSQL extension) for lexical search avoids introducing a dedicated search engine (Elasticsearch/OpenSearch) that CLAUDE.md's "no unnecessary infrastructure" principle would otherwise rule out.

**Consequences / Trade-offs**
- (+) Ranking behavior is fully deterministic, unit-testable without any live infrastructure, and tunable via configuration alone.
- (+) Every result carries its contributing sources and scores as evidence, satisfying the "evidence-first output" requirement for Sprint 5's future citations.
- (–) A fixed absolute semantic-score floor (`semantic_min_score`) is an imperfect "no relevant result" signal for a small local embedding model on short code chunks — relevant and irrelevant cosine scores can land in overlapping ranges. Documented as a known limitation in `docs/SPRINT_LOG.md`; a proper fix (reranker/relevance classifier) is explicitly deferred, not solved here.
- (–) Lexical search is scoped to symbol/file metadata, not full source text — a query for a literal string or comment inside a function body will not be found lexically (only semantically, if the embedding captures it).
- (–) Genuinely useful V2 capabilities (e.g., technical debt detection) are deferred even where a user might want them sooner — any request to pull one forward must go through the Architecture-First Policy conflict process in `CLAUDE.md`, not be added silently.

---

## ADR-018 — Cross-Encoder Reranking: Implemented, Disabled by Default (Pre-Sprint-5 Hardening Pass)

**Status:** Accepted

**Context**
Before Sprint 5, ADR-017's fusion formula was audited for a genuine, measurable quality gap: does a reranking stage — scoring candidates against the query's actual text, something fusion's cosine/trigram/relationship-type scores never do — materially improve retrieval quality, and at what latency cost? "Latency is a first-class design constraint" is stated explicitly in both the Sprint 4 and this hardening pass's briefs, so the answer had to come from a real benchmark, not intuition.

**Decision**
Implement cross-encoder reranking (`app/retrieval/reranking.py`, `Xenova/ms-marco-MiniLM-L-6-v2` via `fastembed` — no new dependency) behind the same provider-interface pattern as Sprint 3's embedding provider, applied only to fusion's top candidate pool (config-bounded) with per-candidate text truncated before scoring (cross-encoder cost scales roughly quadratically with sequence length). Ship it fully wired — config toggle, per-request API override, cache-key-aware — but with `RetrievalSettings.reranking_enabled` defaulting to `False`.

**Rationale (from the actual benchmark, live, `miguelgrinberg/microblog`)**
- At full chunk length (up to 3,500 chars) over a pool of 20: 4,900–8,000ms per query (20–30x the 211ms fusion-only baseline) for +4.8% MRR. Not a defensible default under a stated latency-first constraint.
- Retuned (800-char truncation, pool of 10): 1,538ms (~7.3x baseline) for MRR 0.775 → 1.000 (every correct answer ranked #1). A real improvement, but Recall@K — whether the correct evidence is present in the top-K *at all* — was already 1.000 without it (once the deterministic test-intent fix, see below, closed Sprint 4's one gap). Sprint 5 will reason over the whole top-K evidence set, not solely rank #1, so the marginal value of near-perfect internal ordering is lower than raw retrieval latency.
- A separate, deterministic, zero-latency-cost fix (`query_has_test_intent` + a test-file-path boost in `fuse_and_rank`) closed the one concrete quality gap Sprint 4 measured (the "which tests relate to X" case) without needing the reranker at all — reinforcing that the reranker's marginal contribution, at this stage, is ordering polish rather than correctness.

**Consequences / Trade-offs**
- (+) A materially better reranking path exists, fully tested and one config flag or one query parameter away, for whenever a use case justifies the latency (e.g., a future "deep research" mode, or if Sprint 5 evidence shows rank-order sensitivity that fusion-only can't fix).
- (+) Nothing about Sprint 5's `RetrievalService.query()` contract changes if reranking is later flipped on — it's purely internal to the pipeline.
- (–) The `semantic_min_score` limitation documented in ADR-017 remains technically true in isolation; it no longer matters end-to-end only because the test-intent fix addressed the specific case it was blocking, not because it was itself resolved.
- (–) Query understanding (rule-based tokenization) and structural retrieval (one-hop only) were both re-evaluated in this pass and reconfirmed as sufficient for the current use case — see `docs/SPRINT_LOG.md`'s hardening-pass section for the reasoning; neither was pulled forward from Sprint 5 or expanded, per the Architecture-First Policy.

---

## ADR-019 — AI Engine Orchestration: LangGraph Boundary and Module Layout (Sprint 5)

**Status:** Accepted

**Context**
Sprint 5 required transforming Retrieval's evidence into a grounded, cited answer via a LangGraph-orchestrated pipeline (per the frozen stack, ADR-015), while strictly preserving every Sprint 0–4 module boundary — no duplicating Retrieval/Knowledge logic, no direct Postgres/Qdrant access from the AI module, no LangChain retrieval/agent framework. The `app/ai/` skeleton (created empty in Sprint 0.1: `engine/{intent,retrieval,context,reasoning,verification,formatter,orchestrator}.py`, plus `graph/`, `llm/`, `memory/`, `prompts/`, `schemas/`, `exceptions/`, `services/`) needed a concrete contract for each file.

**Decision**
- `app/ai/engine/orchestrator.py` is the **only file in the codebase that imports LangGraph** — it builds and compiles the `StateGraph`, registers every other `engine/*.py` stage as a thin node, and owns the one bounded conditional edge (the verification retry loop, capped at `AISettings.max_verification_retries`, default 1).
- `app/ai/graph/state.py` holds only the `AIGraphState` TypedDict (the data contract flowing through nodes) — kept separate from the graph's control-flow logic so the state shape can be depended on without pulling in LangGraph.
- Every other `ai/engine/*.py` stage (`intent`, `retrieval`, `context`, `reasoning`, `verification`, `formatter`) is a plain async function with zero orchestration-framework dependency.
- `ai/services/ai_service.py` (`AIOrchestratorService`) is the DI entry point `ai/api.py` depends on — mirrors `RetrievalService`/`KnowledgeService` exactly, and owns everything that wraps the pipeline (cache lookup/write, repository/indexed-state validation, the hard total-timeout, conversation persistence) rather than the pipeline's internal logic.
- `ai/engine/retrieval.py` calls `RetrievalService.query()` directly and unmodified — semantic/lexical/structural/fusion/caching/reranking are never reimplemented; only intent-based `sources`/`top_k` tuning is added.
- Chunk source text (never persisted, per Sprint 3) is read via `app.retrieval.reranking.read_candidate_text`, reused rather than reimplemented a third time.

**Rationale**
- Confining LangGraph to one file makes the "LangGraph owns orchestration/state transitions only" rule (spec §19) mechanically enforceable — a code reviewer only has one file to check.
- `langgraph`'s `langchain-core` transitive dependency is pre-approved by ADR-015 (LangGraph is already named in the frozen stack); the codebase never imports anything from `langchain-core`/`langchain` directly — only `langgraph.graph.StateGraph`/`START`/`END`.
- Mirroring the established `RetrievalService`/`KnowledgeService` DI pattern for `AIOrchestratorService` means `ai/api.py` looks exactly like `retrieval/api.py`/`knowledge/api.py` — no second API architecture, no new pattern to learn.

**Consequences / Trade-offs**
- (+) The orchestration framework is swappable in principle without touching any stage's logic or the API contract — only `orchestrator.py` and `graph/state.py` would change.
- (+) Every stage is independently unit-testable with plain function calls and monkeypatching, with no LangGraph test harness needed (see `test_ai_orchestrator.py`, which does exercise the real compiled graph, but only mocks the two stage functions that touch external services).
- (–) `ai/services/` vs. `ai/engine/orchestrator.py`'s division of "pipeline wrapping" vs. "pipeline internals" is a judgment call made within an empty skeleton, not dictated by the spec — documented here as the resolution, not asked as a question, since it was reversible and internal.

---

## ADR-020 — Verification Gate: Deterministic-Only, No Second LLM Call (Sprint 5)

**Status:** Accepted

**Context**
Spec §8 requires a verification gate as "a critical component" but explicitly warns: "do not allow verification to become another uncontrolled LLM hallucination layer." A second LLM call to "check" the first LLM's answer would add latency, cost, and a new (unverifiable) source of error, without a stronger correctness guarantee than a properly-scoped deterministic check.

**Decision**
`app/ai/engine/verification.py` performs deterministic, regex-based extraction of every file-path-shaped, `symbol()`-shaped, and `line(s) N[-M]`-shaped citation in the LLM's answer text, and checks each one against the *exact* evidence set the LLM was given (`file_path`, `symbol_name`, `start_line`/`end_line` — all already-verified, non-fabricated fields from `RetrievalService`/Sprint 2A's parsed symbols). No LLM call is involved in verification. A sufficiency pre-check (`pre_check_evidence_sufficiency`) runs *before* reasoning, short-circuiting to `INSUFFICIENT_EVIDENCE` without spending an LLM call when evidence is empty or below a relevance floor.

**Rationale**
- Every field being checked against is either a database-derived fact (Sprint 2A symbol data) or a `RetrievalService` score — never another LLM's opinion — so verification result correctness doesn't compound with model uncertainty.
- A citation-extraction approach (rather than a full NL claim-verification approach) is intentionally conservative: it catches the single highest-value failure mode (a fabricated file/symbol/line reference) without attempting the much harder, genuinely AI-complete problem of verifying arbitrary prose claims — which would itself require an LLM and reintroduce the exact risk this ADR avoids.
- Zero added latency cost beyond the regex/set-membership checks themselves (single-digit milliseconds, confirmed in live validation).

**Consequences / Trade-offs**
- (+) Verification is exactly as reliable as the evidence data it checks against — which is Sprint 2A/2B/4's already-tested parsed/retrieved data, not a new trust surface.
- (+) `CONTRADICTED`/`INSUFFICIENT_EVIDENCE` results are handled by a bounded retry (broadened retrieval + a stricter re-prompt, capped at 1 retry) and, on final failure, a deterministic downgrade — the answer is never silently returned as if fully supported.
- (–) A prose claim with no extractable file/symbol/line citation at all is treated as `SUPPORTED` by default (e.g., "this repository is written in Python") — the gate cannot catch a fabricated claim that names no verifiable repository artifact. Documented as a known, accepted scope limit, not a gap to close with a second LLM call.
- (–) Live validation showed real answers sometimes score `PARTIALLY_SUPPORTED` (a genuine model citation not exactly string-matching evidence, e.g. paraphrased line ranges) — this is treated as correct, honest behavior, not a bug to suppress.
