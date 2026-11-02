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
| [017](#adr-017--hybrid-retrieval-fusion-sprint-4) | Hybrid Retrieval Fusion (Sprint 4) |
| [018](#adr-018--cross-encoder-reranking-implemented-disabled-by-default-pre-sprint-5-hardening-pass) | Cross-Encoder Reranking: Implemented, Disabled by Default (Pre-Sprint-5 Hardening Pass) |
| [019](#adr-019--ai-engine-orchestration-langgraph-boundary-and-module-layout-sprint-5) | AI Engine Orchestration: LangGraph Boundary and Module Layout (Sprint 5) |
| [020](#adr-020--verification-gate-deterministic-only-no-second-llm-call-sprint-5) | Verification Gate: Deterministic-Only, No Second LLM Call (Sprint 5) |
| [021](#adr-021--append-only-report-rows-with-a-widened-check-constraint-sprint-6) | Append-Only Report Rows with a Widened CHECK Constraint (Sprint 6) |
| [022](#adr-022--evidenceconfidence-as-a-distinct-vocabulary-from-verificationstatus-sprint-6) | `EvidenceConfidence` as a Distinct Vocabulary from `VerificationStatus` (Sprint 6) |
| [023](#adr-023--report-synthesis-reuses-ai-engine-components-not-the-ask-langgraph-sprint-6) | Report Synthesis Reuses AI Engine Components, Not the `/ask` LangGraph (Sprint 6) |
| [024](#adr-024--deterministic-graph-data-as-the-sole-source-of-truth-for-mermaid-diagrams-sprint-6) | Deterministic Graph Data as the Sole Source of Truth for Mermaid Diagrams (Sprint 6) |
| [025](#adr-025--indexing-pipeline-performance-pass-batching-noise-filtering-duplicate-job-prevention-celery-conflict-flagged-not-implemented) | Indexing Pipeline Performance Pass: Batching, Noise Filtering, Duplicate-Job Prevention (Celery Conflict Flagged, Not Implemented) |
| [026](#adr-026--celery-based-indexing-supersedes-adr-011) | Celery-Based Indexing (Supersedes ADR-011) |

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

**Status:** Superseded by ADR-026 (project owner explicitly approved revisiting this decision; see ADR-026 for the Celery-based replacement). The context/decision/rationale below is left exactly as originally recorded — never rewritten — per this document's own convention; ADR-026 is the current source of truth for indexing-pipeline execution.

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

---

## ADR-021 — Append-Only Report Rows with a Widened CHECK Constraint (Sprint 6)

**Status:** Accepted

**Context**
Sprint 6 needed a persistent representation for five report types (Repository Overview, Architecture, Dependency & Risk, Codebase Health, Developer Onboarding Guide), safely regeneratable, with regeneration never corrupting the last good result and repository re-indexing correctly invalidating stale reports (spec §11/§12). The `reports` table already existed (Sprint 0B skeleton: `report_type`, `content`, zero production rows — the same situation `conversations` was in pre-Sprint-5, per ADR context in `b4bca69510a2`) with a `CHECK` constraint on `report_type` limited to `('summary', 'onboarding', 'architecture', 'impact')`.

**Decision**
Extend the existing `Report` model additively rather than building a parallel storage system: widen `VALID_REPORT_TYPES` to add `dependency_risk` and `health` (mapping Sprint 6's five report types onto `summary`/`architecture`/`dependency_risk`/`health`/`onboarding`; `impact` stays reserved and unused — a distinct future single-PR/diff-impact feature per ADR-016, never repurposed for the Dependency & Risk report despite the naming similarity). Add a `status` lifecycle column (`pending`/`generating`/`ready`/`failed`) plus nullable structured-rendering columns (`title`, `summary`, `sections`, `evidence`, `diagrams`, `generation_metadata`, `repository_version`, `generated_at`, `error_message`). Reports are **append-only**: every generation attempt inserts a new row; nothing is ever updated in place. "The latest report" of a given `(repository_id, report_type)` is defined purely by `created_at` recency, and only a `status="ready"` row is ever served as the current report from `GET`; a `status="failed"` row is retrievable for diagnostics but never silently treated as valid. The existing CHECK-constraint-widening migration follows the same raw-DDL pattern (`op.execute` `DROP CONSTRAINT`/`ADD CONSTRAINT`) established in `b4bca69510a2` for `conversations.verification_status`, required because `CheckConstraint(..., name="report_type")` resolves to `ck_reports_report_type` under `models/base.py`'s naming convention — `op.create_check_constraint` would double-prefix it on an already-existing table.

**Rationale**
- Append-only writes make "a failed regeneration attempt corrupts the last good report" structurally impossible — there is no `UPDATE` path to a `ready` row at all, so a crash mid-generation can only ever produce an additional `failed` row alongside the still-intact previous `ready` one.
- Reusing the existing `Report`/`reports` table (rather than introducing a second reports store) respects CLAUDE.md §9's three-database freeze and the spec's explicit instruction to verify Sprint 0–5 ownership decisions before changing persistent schema.
- A `repository_version` fingerprint (reusing `app.retrieval.cache.get_corpus_version`'s exact format) on each row makes staleness detection a pure string comparison against the repository's current version, with no separate invalidation bookkeeping.
- Keeping `content` (the original column) `NOT NULL` and populating it with a deterministic textual rendering of the same structured data preserves the pre-Sprint-6 contract without forcing a breaking column removal.

**Consequences / Trade-offs**
- (+) Regeneration, concurrent generation, and partial-failure handling all reduce to "insert one more row" — no locking, no in-place mutation races to reason about.
- (+) A full generation history is available for free (`GET .../reports?latest_only=false`), useful for auditing report-quality drift over time without any extra schema.
- (–) The table grows monotonically with every regeneration (including failed attempts) — acceptable at V1's expected report-generation frequency (developer-triggered, not continuous); a retention/pruning policy is the natural next step if this becomes a real storage concern, not solved here.
- (–) `impact` remains a defined-but-unused `VALID_REPORT_TYPES` value for a second sprint running — an intentional reservation, not dead code to clean up, per ADR-016's scope boundary between this sprint's Dependency & Risk report and the distinct future single-PR/diff Impact Analysis feature.

---

## ADR-022 — `EvidenceConfidence` as a Distinct Vocabulary from `VerificationStatus` (Sprint 6)

**Status:** Accepted

**Context**
Spec §10 requires every report statement to carry an explicit confidence label (`VERIFIED`/`DERIVED`/`PARTIAL`/`INSUFFICIENT_EVIDENCE`), distinguishing deterministic repository facts from derived analysis from AI interpretation. Sprint 5 already defined `app.ai.schemas.verification.VerificationStatus` (`SUPPORTED`/`PARTIALLY_SUPPORTED`/`INSUFFICIENT_EVIDENCE`/`CONTRADICTED`) for a related but narrower purpose: whether one `/ask` answer's citations verify against the evidence it was given.

**Decision**
Define a new, separate enum, `app.reports.schemas.EvidenceConfidence`, rather than reusing or renaming `VerificationStatus`. `VerificationStatus` remains AI-Engine-only, describing one LLM answer's citation-verification outcome. `EvidenceConfidence` describes the *provenance* of one report section/statement, with an explicit mapping (`app.reports.evidence.map_verification_to_confidence`) from the former to the latter wherever AI-synthesized report prose needs a confidence label:
- A deterministic fact read directly from the database (a file count, an entry point path, a dependency-hotspot row) → `VERIFIED`.
- A fact computed by combining/interpreting deterministic data without AI (a directory rollup, a risk classification, a diagram) → `DERIVED`.
- AI-synthesized prose whose extracted citations fully verify against the evidence set (`VerificationStatus.SUPPORTED`) → `DERIVED` (the underlying facts were confirmed, even though the prose itself is model-generated).
- AI-synthesized prose with some unverified citations (`VerificationStatus.PARTIALLY_SUPPORTED`) → `PARTIAL`.
- AI-synthesized prose that could not be grounded at all (`VerificationStatus.INSUFFICIENT_EVIDENCE`) or whose citations are entirely fabricated (`VerificationStatus.CONTRADICTED`) → `INSUFFICIENT_EVIDENCE`, and the returned content is explicitly prefixed with an unverified-interpretation flag rather than silently presented as fact.

**Rationale**
- Collapsing the two enums would either narrow `VerificationStatus`'s meaning (a `/ask` answer's citation check is not the same claim as "how was this report section produced") or force reports to inherit AI-Engine-specific states (`CONTRADICTED`) that don't map cleanly onto pure database facts, which are never "contradicted," only present or absent.
- A `CONTRADICTED` verification result and an `INSUFFICIENT_EVIDENCE` one both mean the same thing for a report consumer — "do not treat this as fact" — so collapsing them into one `EvidenceConfidence.INSUFFICIENT_EVIDENCE` value is a deliberate simplification for the reporting surface, not a loss of information (the underlying `VerificationStatus` is still recorded in `generation_metadata` for debugging).
- Keeping the mapping as one small, explicitly documented function (rather than scattering the equivalence across generators) makes the confidence-labeling rule auditable in one place.

**Consequences / Trade-offs**
- (+) Report consumers (including the eventual frontend) reason about exactly four confidence states regardless of whether a section's content came from the database or from the LLM.
- (+) `VerificationStatus`'s Sprint 5 meaning and callers are completely undisturbed — zero risk of an accidental Sprint 6 change to `/ask` behavior.
- (–) Two conceptually related but distinct enums now exist in the codebase; a reviewer must know which one applies where. Mitigated by keeping them in clearly separate modules (`app.ai.schemas.verification` vs. `app.reports.schemas`) and documenting the mapping in one function's docstring.

---

## ADR-023 — Report Synthesis Reuses AI Engine Components, Not the `/ask` LangGraph (Sprint 6)

**Status:** Accepted

**Context**
Spec §9 requires reports to use AI "only where it provides meaningful value" and explicitly forbids introducing a second LLM framework or bypassing the existing LangGraph architecture (CLAUDE.md §7/ADR-019: LangGraph orchestration is confined to `app.ai.engine.orchestrator`, built for the `intent → retrieve → context → reason → verify → format` pipeline shape of free-text Q&A). Report synthesis needs one narrow capability from that stack — turning a batch of already-assembled, already-verified facts into developer-friendly prose for several named sections in a single call — which does not fit the `/ask` graph's per-query, single-answer shape at all.

**Decision**
`app.reports.synthesis` reuses two Sprint 5 AI Engine **components** directly, never the compiled graph: `app.ai.llm.provider.get_llm_provider()`/`complete_with_retry()` for the raw LLM call (same provider abstraction, same Groq/Ollama backends, same retry/timeout policy — ADR-014 unaffected), and `app.ai.engine.verification.verify_answer()`'s regex-based citation-extraction mechanics, reused as-is to grounding-check AI-synthesized report prose against the report's own evidence set. No new prompt-orchestration framework, no second LangGraph instance, and no import of `app.ai.engine.orchestrator` or `app.ai.graph.state.AIGraphState` from `reports/`. At most one LLM call is made per report generation, batching every eligible section's narrative need into a single structured-JSON-output prompt (spec §14's "no unnecessary sequential LLM calls").

**Rationale**
- The `/ask` graph's stages (intent classification, per-query retrieval, a single question/answer turn, a bounded verification retry loop) solve a different problem than "synthesize prose for N known sections from M already-collected facts in one shot" — forcing report synthesis through it would mean either calling `/ask` N times (violating the single-call latency budget) or contorting the graph's state shape to fit a use case it wasn't designed for.
- Reusing the LLM provider abstraction and the verification mechanics (rather than reimplementing either) means report synthesis inherits Sprint 5's already-tested retry/timeout/citation-checking behavior for free, and any future provider swap (ADR-014) automatically applies to reports too.
- A single batched prompt, parsed as one JSON object, keeps latency bounded and predictable (measured live: ~1.3–2.4s per report needing synthesis, vs. Sprint 5's per-question `/ask` latency) and avoids the "second uncontrolled LLM hallucination layer" risk ADR-020 already rejected for verification — reused here rather than re-litigated.

**Consequences / Trade-offs**
- (+) Zero duplication of LLM-calling or citation-verification logic between `ai/` and `reports/` — a bugfix or provider change in either reused component benefits both call sites automatically.
- (+) Malformed/non-JSON LLM output degrades to a deterministic-only report (`generation_metadata.ai_synthesis_failed=true`), never a crash — verified live via `test_reports_synthesis.py`'s malformed-output cases and confirmed structurally impossible to silently fabricate content, since every synthesized section is still grounding-checked before being attached.
- (–) `dependency_risk` and `health` report types deliberately never request AI synthesis at all (spec §9's "do not make every report require an LLM call if deterministic generation is sufficient") — an intentional asymmetry across report types, not an oversight; documented in each generator's module docstring.

---

## ADR-024 — Deterministic Graph Data as the Sole Source of Truth for Mermaid Diagrams (Sprint 6)

**Status:** Accepted

**Context**
Spec §15 requires architecture diagrams generated "from actual repository structure and relationship data" and explicitly forbids letting the LLM "freely hallucinate diagrams." Sprint 2B's `depends_on`-type relationships and `RepositoryIntelligence.dependency_hotspots` already provide real, resolved module-level dependency edges — the only question was how much of diagram construction, if any, the optional AI synthesis step (ADR-023) should be allowed to influence.

**Decision**
`app.reports.mermaid` builds both diagram types (`build_module_diagram`, `build_dependency_flow_diagram`) as pure, deterministic functions over real `depends_on` edges and `dependency_hotspots` rows — no LLM call anywhere in the diagram-construction path. Node aggregation (file paths and dotted module paths rolled up to a coarse "module" granularity), node-count capping (top ~25/~15 by dependency weight), and edge selection are all computed before AI synthesis ever runs; the synthesis stage (when it runs at all) only ever adds human-readable prose *about* an already-built diagram's contents into a separate report section — it is never given the ability to add, remove, or relabel a Mermaid node or edge. Two small, dedicated, unit-tested helpers (`_sanitize_node_id`, `_sanitize_mermaid_label`) guarantee output safety (collision-free alphanumeric ids, escaped label characters) independent of the diagram-construction logic.

**Rationale**
- Making the graph data structurally unreachable from the LLM call (rather than merely instructing the LLM not to hallucinate edges) is a stronger guarantee than a prompt rule — the diagram is fully built and validated before any AI code path executes.
- Deterministic construction makes diagrams unit-testable with fixture data alone (`test_reports_mermaid.py`): valid `flowchart` header, bounded node count, no unescaped label characters, no edge referencing an undeclared node — none of which would be reliably testable if diagram text came from an LLM.
- A capped, weight-ranked node set (rather than rendering every module) keeps diagrams legible for large repositories and is marked explicitly partial (a trailing Mermaid comment) rather than silently dropping data — satisfying spec §4's "where the graph is incomplete, explicitly mark the diagram... as partial."

**Consequences / Trade-offs**
- (+) A diagram can never contain a fabricated file, module, or relationship — every node and edge traces back to a real `File`/`Relationship`/`RepositoryIntelligence` row, verified live against `miguelgrinberg/microblog`'s actual dependency structure.
- (+) Diagram generation costs no LLM latency or tokens at all — it runs as part of the deterministic-collection phase regardless of whether AI synthesis is enabled or fails for that report.
- (–) Diagram node/edge labels are the raw module-path strings (e.g. `app.models`), not LLM-polished descriptions — acceptable given spec §15's explicit "LLM may provide labels/descriptions but must not invent graph edges" allowance was not exercised in this sprint (no generator currently asks the LLM to relabel diagram nodes); a future enhancement could pass the already-built node list to synthesis for label suggestions without changing this ADR's core guarantee.

---

## ADR-025 — Indexing Pipeline Performance Pass: Batching, Noise Filtering, Duplicate-Job Prevention (Celery Conflict Flagged, Not Implemented)

**Status:** Accepted. (The Celery conflict this ADR flagged was subsequently taken to the project owner, who explicitly approved superseding ADR-011 — see **ADR-026**, which implements Celery on top of everything this ADR describes. Nothing in this ADR is reversed or reduced by that follow-up; it remains the accurate record of the non-Celery pass.)

**Context**
A performance/architecture overhaul of the indexing pipeline was requested, with four parts: (1) move indexing onto Celery, (2) broaden noise filtering, (3) optimize the parse/chunk/embed/upsert pipeline, (4) validate with real benchmarks and tests. Part (1) directly contradicts ADR-011 and ADR-015/016 (Celery explicitly, deliberately excluded from V1, with the stated revisit path being "the Architecture-First Policy conflict process," not a silent implementation) — per CLAUDE.md's Architecture-First Policy, that part was **not implemented**; it is flagged here and in the session's final report for explicit user approval, not built around. Everything else in the request is implementable without touching the frozen stack (ADR-011's own "no new infrastructure" framing anticipates exactly this: push correctness/perf as far as the single-process model allows first).

**Decision**
Within the existing `BackgroundTask` model:
- **Noise filtering** (`ingestion/utils.py::scan_directory`): broadened the hardcoded directory/filename/suffix exclusion lists (dependency dirs across languages, build output, VCS/tooling dirs, binaries/media/archives/lockfiles/minified output), added `.gitignore`-awareness via `pathspec` (new, minimal, pure-Python dependency — not infrastructure, so outside ADR-015's "new framework/database/provider" freeze), and added a configurable scan-time size cap (`IngestionSettings`, env-driven). Every exclusion is now inspectable: `ScanResult.excluded_by_reason`/`excluded_samples`, persisted on `RepositoryWorkspace` (new nullable-by-default columns via a normal additive Alembic migration — not a frozen-architecture change, an ordinary schema evolution) and surfaced via `GET .../workspace`. Knowledge's previously-separate, narrower `_EXCLUDED_KNOWLEDGE_FILENAMES`/`_EXCLUDED_KNOWLEDGE_SUFFIXES` lists (from the prior OOM fix) now import and reuse Ingestion's lists as the single source of truth, keeping Knowledge's own 512KB embedding-specific size cap as a separate, narrower, defense-in-depth check.
- **Parsing stage**: `Repository.indexing_progress` is now persisted at most ~20 times per run (plus always on the final file) instead of once per file; the per-file `content_hash` write no longer does its own separate flush/refresh round trip (the one transaction's eventual commit persists it regardless). Both were measured, concrete per-file DB round-trips, not hypothetical.
- **Knowledge stage**: `KnowledgeService.index_repository` now pools files into configurable batches (`LLMSettings.knowledge_file_batch_size`, default 25) and, within a batch, issues one pooled Redis cache lookup, one Qdrant delete, one Qdrant upsert, and one Postgres chunk-insert instead of one of each per file. The embedding call itself is further sub-batched to `embedding_batch_size` texts per `provider.embed()` call (not left as one unbounded call per file-batch) — live validation on a real repository (`sujeet-agrahari/nodejs-microservices-example`) showed pooling an entire 25-file batch's misses into one unbounded `embed()` call reproduced the exact ONNX `BFCArena` OOM class the prior sprint's 512KB per-file cap was built to prevent, via aggregate chunk count instead of a single oversized file; explicit sub-batching is the fix, documented at its call site. File-level failure isolation is coarsened to batch-level for the embed/upsert/DB-write step specifically (a pooled call's failure fails every file in that batch, logged and counted, repository indexing continues) — a deliberate, documented trade-off of pooling calls across files.
- **Duplicate-job prevention** (in scope even without Celery): `WorkspaceService.request_indexing` now rejects (`409`, `IndexingAlreadyInProgressError`) a second indexing trigger while `Repository.indexing_status == "indexing"`, and `run_parsing_pipeline`'s crash handler now marks the repository `"failed"` (via a fresh recovery session, since the crashed session is rolled back) rather than leaving it stuck reporting `"indexing"` forever — without this, a crash would have permanently blocked ever re-triggering indexing once the new guard existed. Live-verified: a second `POST .../index` while the first run was still in flight correctly returned 409.
- Verified, not changed: `get_embedding_provider()`'s `@lru_cache` already loads the model exactly once per process (confirmed live: one `"Loaded embedding model..."` log line per process, not per file or per run) — no fix was needed there, only confirmation.

**Rationale**
- Every change here is additive/internal to a module already responsible for the behavior it changes (Ingestion's scanner, Knowledge's indexing loop, the parsing loop's own progress writes) — no module boundary, API contract, or data-ownership rule from CLAUDE.md §6 was touched.
- The `pathspec` dependency and the new `repository_workspace` columns are ordinary feature-implementation choices (a library and an additive migration), not stack or schema *ownership* changes requiring the Architecture-First Policy's stop-and-ask — they were made directly, per this ADR's own standing authorization for implementation-detail choices.
- The embed-call sub-batching fix is included in this same ADR rather than filed separately because it was discovered *during* this pass's own live validation of the batching change it fixes — recording cause and fix together keeps the trade-off honest (batching has a real, caught failure mode, not an unqualified win).

**Consequences / Trade-offs**
- (+) Real, measured before/after numbers exist for this repository (see the session's final report) — this ADR intentionally does not restate them, to avoid the numbers going stale here while staying current in benchmark output.
- (+) Incremental re-indexing (content-hash fast path) continues to work correctly under batching — live-verified: an unmodified repository re-indexes in under a second with every file skipped as unchanged; a 2-file change re-indexes in a few seconds with exactly those files' chunks refreshed.
- (–) Celery — the task's primary objective — remains unimplemented pending explicit user approval to supersede ADR-011/015/016. Indexing speed only improves as far as a single-process, single-worker model allows; cross-repository/cross-stage concurrency bounding (explicitly requested) is not meaningfully achievable without it. This is the first, cheapest-available win, not a replacement for that decision.
- (–) Parsing-stage incremental skip (reusing a prior run's symbols/relationships for an unchanged file) was evaluated and **not implemented**: `relationships` rows aren't tied to an originating file id, so safely skipping re-parse of an unchanged file would either lose its edges from the graph or require a schema change (`relationships.source_file_id` or equivalent) — exactly the kind of persistent-schema change this session's own instructions say to stop and ask about rather than add silently. Flagged as the clearest next-step candidate, not solved here.
- (–) Batch-level (not file-level) failure isolation during the embed/upsert step is a real, if narrow, regression in failure granularity versus the pre-pass per-file isolation — accepted as the cost of pooling calls across files; revisit if batch-level failures prove operationally disruptive at larger scale.

---

## ADR-026 — Celery-Based Indexing (Supersedes ADR-011)

**Status:** Accepted. The project owner explicitly approved revisiting ADR-011 after ADR-025 flagged the conflict (per the Architecture-First Policy) rather than silently implementing it. This ADR supersedes ADR-011; ADR-011's original content is left unmodified, marked superseded, and points here.

**Context**
ADR-011 froze indexing on FastAPI `BackgroundTasks`, explicitly citing "no multiple workers to distribute work across" and deferring Celery to exactly this situation: "the first candidate to revisit... if/when the platform needs to scale indexing throughput independently of API traffic." ADR-025's pipeline-optimization pass (batching, noise filtering) materially reduced indexing time within the single-process model, but could not address the one thing that model structurally cannot do: run two independent repositories' indexing pipelines with genuine wall-clock overlap, since every BackgroundTask and ASGI request share one process's one event loop, and the CPU-bound stages (Tree-sitter parsing, ONNX embedding inference) dominate total time regardless of `await` points. With explicit approval, this ADR implements Celery to solve exactly that.

**Decision**
- **Broker/backend**: the existing Redis instance, reused — but on its **own logical Redis DB index** (`CelerySettings.celery_redis_db`, default `1`), never `RedisSettings.redis_db` (`0`, the embedding/AI/retrieval/reports cache's). Broker messages and cache entries are different workloads with different loss tolerances (a dropped indexing job is not a cheap recompute the way a dropped cache entry is); separating them costs nothing extra (still one Redis process) and keeps ADR-006's "three data stores, each with one job" model intact in spirit even though Celery itself is new.
- **Task definitions** live in `app/ingestion/tasks.py` (`run_indexing_task`, `run_knowledge_reindex_task`), not `core/` — a Celery task body is exactly as much business logic as the `BackgroundTask` function it replaces, so it stays next to the logic it wraps (`parsing_service.run_parsing_pipeline`, `knowledge/pipeline.run_knowledge_indexing_pipeline`, both reused unmodified, not rewritten). `app/core/celery_app.py` only builds/configures the `Celery` app instance — infrastructure, not logic, per CLAUDE.md §6.
- **API contract preserved**: `POST /repositories/{id}/index` and `POST /repositories/{id}/knowledge/reindex` keep their exact request/response shapes; `indexing_status`/`indexing_progress` on `Repository` remain the frontend's polling source of truth, written by the task via the same `repository_db.save()` calls the BackgroundTask version used. One additive field, `celery_task_id` (new nullable column), and one additive endpoint, `POST /repositories/{id}/index/cancel`, were added — neither changes any existing contract.
- **Duplicate-job prevention, two layers, deliberately**: the existing Postgres `indexing_status` check in `WorkspaceService.request_indexing` remains as a cheap, fast, user-facing 409 for the common case (re-clicking "index"). The *actual*, race-free guarantee is a new Redis-based distributed lock (`app/ingestion/indexing_lock.py`: atomic `SET NX PX` acquire, Lua compare-and-delete release) acquired by the **task itself**, not the API layer — closing a real TOCTOU race the status check alone has (two near-simultaneous requests can both read "not indexing" before either commits). Live-verified under genuine concurrent Celery task dispatch (bypassing the API guard entirely): two tasks enqueued for the same repository, one ran, the other logged "another task already holds this repository's indexing lock" and returned untouched — no corruption, no duplicate Qdrant points.
- **Retries**: a pipeline failure is no longer swallowed by `run_parsing_pipeline`/`run_knowledge_indexing_pipeline` (both now `raise` after recording `indexing_status="failed"`, instead of only logging) — the task wrapper catches it, releases its lock in a `finally`, and calls `self.retry()` with backoff (`CelerySettings.celery_max_retries`, `celery_retry_backoff_seconds`), confirmed via a real `celery.exceptions.Retry` raised in test.
- **Cancellation**: the new endpoint revokes the Celery task (`terminate=True`/SIGTERM — an indexing task has no cooperative cancellation checkpoint to poll), proactively clears the repository's lock (a terminated task's own `finally` may not run), and marks the repository `failed` with an explicit message. Live-verified: cancel mid-run, then successfully re-trigger indexing immediately after, with no stuck lock or stuck `"indexing"` status.
- **Bounded concurrency across repositories**: Celery worker concurrency (`--concurrency`, `CelerySettings.celery_worker_concurrency`, default 4) bounds how many whole-repository tasks run at once. **Bounded concurrency within a stage** (e.g. parallel Tree-sitter parsing across one repository's own files) was evaluated and **not implemented** in this pass — out of scope for a Celery-specific follow-up; each task still runs its one repository's parse→intelligence→knowledge sequence sequentially, unchanged from ADR-025.
- **Pool choice is load-bearing and documented explicitly**, because of a real bug this pass caught live: `app.db.postgres`/`app.db.redis`/`app.db.qdrant` all expose process-wide `@lru_cache`'d async clients, correct for the ASGI server (one process, one event loop, for its whole lifetime) but incompatible with a naive `asyncio.run(coro)` per task call, which creates and tears down a fresh loop every time — the cached Postgres engine (asyncpg connections are loop-bound) stays attached to whichever loop happened to build it on a worker's *first* task, and every later task in that same process/thread then fails with `RuntimeError: Event loop is closed`. Fixed in `app.ingestion.tasks._get_worker_event_loop`: one persistent loop per OS process/thread, created once, reused for every task that process/thread ever runs — matching the ASGI app's own lifetime assumption for those same cached clients. This makes **process-based** concurrency (Celery's default `prefork` pool, which Docker's `celery-worker` service uses) the only fully supported concurrency model; `--pool=threads`/`eventlet`/`gevent` (multiple tasks truly concurrent *within* one process) are not safe with this client-caching pattern and are not used anywhere in this project's run commands. Windows bare-metal local dev (no `fork()`) uses `--pool=solo` (Celery's own standard recommendation there); real local concurrent-repository testing is done with **multiple separate `--pool=solo` processes**, which is both Windows-safe and exactly how `prefork`'s child processes behave (each its own OS process, each lazily builds its own fresh clients on first use).
- **Per-worker-process embedding warm-up**: a second real bug this pass's own concurrency benchmark caught — each worker process pays its *own* first-real-embed ONNX warm-up cost independently (observed: 125 seconds on one freshly started worker, on top of the ~2s model-load time already logged separately), since `get_embedding_provider()`'s `@lru_cache` is per-process, not shared across workers. Fixed with a `worker_ready`/`worker_process_init` signal handler (`core/celery_app.py::_warm_up_embedding_model`) that loads the model and runs one throwaway `embed()` call at worker startup, moving that cost to worker readiness instead of a user's first real indexing request.

**Rationale**
- Reusing Redis (not adding a new broker like RabbitMQ) keeps the "no unnecessary infrastructure" principle intact — Celery is the one new *framework* this pass adds, not a new *datastore*; the separate logical DB index is a zero-cost, load-bearing-enough-to-document boundary, not a new moving part.
- A task-held distributed lock (not just an API-level status check) is the only approach that is actually race-free under multiple API processes and multiple workers — documented and chosen over relying solely on Celery's own task-uniqueness features, since those are broker-specific/best-effort in community Celery (no built-in exactly-once guarantee), whereas Redis `SET NX` is a well-understood, directly-testable primitive this project already depends on.
- Fixing the event-loop/client-caching bug *in the task layer* (one persistent loop per process) rather than *in the client layer* (e.g., making every `db/*.py` client fresh-per-call) preserves the ASGI app's existing, correct, tested caching behavior untouched — only the new Celery entry point had to adapt to that existing assumption, not the other way around.

**Consequences / Trade-offs**
- (+) Real, measured concurrency benefit on two independent repositories (both the pipeline-optimized `nodejs-microservices-example`, 161 files, and a freshly cloned `expressjs/cors`, 17 files), using warmed workers so the comparison isolates concurrency from one-time startup costs: solo durations 27,536ms and 21,849ms (sum: 49,385ms, the old single-process model's effective floor) vs. 26,029ms wall-clock running both concurrently on two worker processes — a measured **1.9x** speedup, consistent with two independent jobs genuinely overlapping rather than queueing behind each other.
- (+) Verified zero corruption/duplication under real concurrent dispatch: both repositories' Postgres chunk counts (297, 46) matched their Qdrant point counts exactly after the concurrent run; the deliberate same-repository race test left exactly one task's worth of state behind, never two.
- (–) The event-loop-per-process-or-thread constraint means this architecture's concurrency ceiling is "number of worker *processes*," not "worker processes × threads-per-process" — accepted, since fixing it the other way (per-call fresh clients) would cost connection-pooling efficiency the ASGI app currently benefits from, for a concurrency model (in-process threads sharing one asyncio loop's cached async clients) this codebase was never designed around.
- (–) Intra-repository stage parallelism (concurrent Tree-sitter parsing of one repository's own files) remains unimplemented, as does the parsing-stage incremental-skip limitation ADR-025 already flagged (needs a schema change, still not made without separate approval).
- (–) A true distributed lock only moves the duplicate-run risk down to "Redis is unavailable" — acceptable, since Redis is already a hard dependency for this app's cache/session-state (ADR-006) and its unavailability already degrades the system broadly, not newly introduced by this ADR.
