"""Application configuration.

All runtime configuration is loaded from environment variables (and,
for local development, a `.env` file) via ``pydantic-settings``. Each
concern owns its own settings class so a misconfigured subsystem fails
validation with a message that points directly at it, instead of one
monolithic settings object.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal, Optional

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = ".env"


def _split_csv(value: str) -> list[str]:
    """Split a comma-separated env value into a stripped, non-empty list."""
    return [item.strip() for item in value.split(",") if item.strip()]


class AppSettings(BaseSettings):
    """Application metadata, runtime flags, and web-layer configuration.

    ``cors_origins``/``allowed_hosts`` are kept as raw strings (not
    ``list[str]``) because pydantic-settings tries to JSON-decode
    list-typed env values before any validator runs, which rejects a
    plain comma-separated value like ``CORS_ORIGINS=http://localhost:3000``.
    Use the ``*_list`` properties to get the parsed list.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    app_name: str = "CodeSage"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    backend_port: int = 8000
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"
    allowed_hosts: str = "*"
    repository_storage_path: str = "data/repositories"
    # Which part of the app this process runs (ADR-028): "api" serves HTTP and
    # never indexes; "indexer" only runs the job-claim loop plus internal
    # endpoints; "all" is both in one process (local dev / single-container).
    role: Literal["api", "indexer", "all"] = "all"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parsed, comma-separated CORS allow-list."""
        return _split_csv(self.cors_origins)

    @property
    def allowed_hosts_list(self) -> list[str]:
        """Parsed, comma-separated trusted-host allow-list."""
        return _split_csv(self.allowed_hosts)


class DatabaseSettings(BaseSettings):
    """PostgreSQL connection parameters."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "codesage"
    postgres_password: SecretStr = SecretStr("codesage")
    postgres_db: str = "codesage"

    @property
    def async_dsn(self) -> str:
        """Build the SQLAlchemy async DSN for the configured PostgreSQL instance.

        Returns:
            An ``postgresql+asyncpg://`` connection string built from the
            individual host/port/credential fields.
        """
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{self.postgres_password.get_secret_value()}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


class RedisSettings(BaseSettings):
    """Redis connection parameters."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[SecretStr] = None


class CelerySettings(BaseSettings):
    """Celery broker/backend/worker configuration (ADR-026).

    Reuses the existing Redis instance (``RedisSettings``) as both
    broker and result backend, per the project's "no unnecessary
    infrastructure" principle — but deliberately on its **own logical
    Redis DB index** (``celery_redis_db``, default ``1``), never
    ``RedisSettings.redis_db`` (default ``0``, used for the embedding/
    AI/retrieval/reports caches). Broker traffic and cache traffic are
    different workloads with different eviction/durability expectations
    (a lost cache entry is a cheap recompute; a lost broker message is a
    dropped indexing job) — a separate DB index keeps them from ever
    contending over Redis's single keyspace/eviction policy, at zero
    extra infrastructure cost (still one Redis process).
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    celery_redis_db: int = 1
    # Caps concurrent indexing jobs across *independent repositories* —
    # the cross-repository bounded concurrency this pass is required to
    # provide. Passed to the worker as ``--concurrency`` at startup
    # (bare-metal command / Docker service), not read directly by the
    # app, but kept here as the single documented source of truth for
    # the default so both run paths agree with each other without
    # hand-copying a number in two places.
    celery_worker_concurrency: int = 4
    # A single indexing task runs the whole clone-already-done pipeline
    # (parse -> intelligence -> knowledge) sequentially, same as the
    # pre-Celery BackgroundTask did — "concurrency within a stage" (e.g.
    # parallel Tree-sitter parsing across files of the *same* repository)
    # is a separate, not-yet-made change (see ADR-026's Consequences);
    # this setting only bounds how many *whole-repository* tasks a given
    # worker process runs at once.
    celery_task_time_limit_seconds: int = 1800  # hard kill switch for a runaway task (30 min)
    celery_task_soft_time_limit_seconds: int = 1700
    celery_max_retries: int = 2
    celery_retry_backoff_seconds: int = 10
    # TTL for the Redis lock that enforces "only one indexing task per
    # repository at a time" across concurrent workers (not just within
    # one process) — see ADR-026. Set comfortably above
    # ``celery_task_time_limit_seconds`` so a legitimately long-running
    # task is never undercut by its own lock expiring.
    indexing_lock_ttl_seconds: int = 2400


class IndexingSettings(BaseSettings):
    """How indexing work is dispatched and executed (ADR-028).

    ``celery`` keeps the ADR-026 behaviour (local docker-compose). ``postgres``
    uses the ``indexing_jobs`` table as the queue — no broker — which is what
    the hosted free-tier deployment runs.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    indexing_backend: Literal["celery", "postgres"] = "celery"
    # Base URL of the indexer service (e.g. https://codesage-indexer.onrender.com), used by the
    # API role to wake it. Unused when both roles share a process.
    indexer_url: Optional[str] = None
    # A running job must renew its lease at least this often or another worker may take it over.
    indexing_lease_seconds: int = 120
    indexing_heartbeat_seconds: int = 30
    indexing_max_attempts: int = 3  # first try + 2 retries, matching celery_max_retries
    indexing_retry_backoff_seconds: int = 10
    # The wake call runs in the background, and a sleeping free host can take ~1 minute to boot.
    indexer_wake_timeout_seconds: float = 90.0
    # API -> indexer keep-alive pings while a job is active are sent at most this often.
    indexer_ping_min_interval_seconds: int = 30

    @field_validator("indexer_url", mode="before")
    @classmethod
    def _blank_means_unset(cls, value):
        """Treat ``INDEXER_URL=`` as unset and drop a trailing slash."""
        if isinstance(value, str):
            return value.strip().rstrip("/") or None
        return value


class QdrantSettings(BaseSettings):
    """Qdrant connection parameters."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    qdrant_host: str = "localhost"
    qdrant_http_port: int = 6333
    qdrant_grpc_port: int = 6334


class LLMSettings(BaseSettings):
    """LLM and embedding provider configuration.

    LLM fields (Groq primary, Ollama fallback — ADR-014) are
    configuration only: no LLM calls are made until the AI module is
    implemented. The embedding fields are consumed starting Sprint 3
    (Knowledge module).
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    llm_provider: Literal["groq", "ollama"] = "groq"
    groq_api_key: Optional[SecretStr] = None
    groq_model: str = "openai/gpt-oss-120b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    # Provider-facing call tuning (Sprint 5) — stays here with
    # provider/model/credentials, not in AISettings, matching this
    # class's established scope (anything about *how a completion call
    # is made*, vs. AISettings' *pipeline behavior*).
    llm_temperature: float = 0.15  # low: grounded/factual answers, not a chatty "personality"
    llm_max_output_tokens: int = 1024
    llm_timeout_seconds: float = 20.0
    llm_max_retries: int = 2
    llm_retry_backoff_seconds: float = 1.0

    # Embedding provider is intentionally decoupled from the LLM
    # provider above — swapping to a hosted embedding API later only
    # means adding another branch in knowledge/embedding.py, never a
    # settings redesign.
    embedding_provider: Literal["fastembed", "cloudflare"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384
    embedding_batch_size: int = 32
    # Cloudflare Workers AI (ADR-029): the same BGE-small weights hosted,
    # so a 512MB free host never has to load the ONNX model itself.
    cloudflare_account_id: Optional[str] = None
    cloudflare_api_token: Optional[SecretStr] = None
    cloudflare_embedding_model: str = "@cf/baai/bge-small-en-v1.5"
    # Cloudflare defaults to mean pooling, but BGE models are trained for
    # CLS pooling (what the local ONNX model uses). Measured: "cls" gives
    # cosine 1.0000 against the local vectors, "mean" only 0.93-0.99.
    cloudflare_embedding_pooling: Literal["cls", "mean"] = "cls"
    cloudflare_embedding_batch_size: int = 100  # measured: the API accepts at least 1000 per call
    cloudflare_timeout_seconds: float = 30.0
    cloudflare_max_retries: int = 3
    cloudflare_retry_backoff_seconds: float = 1.0
    embedding_cache_ttl_seconds: int = 2_592_000  # 30 days — Redis is a pure perf cache, never the source of truth
    embedding_model_cache_dir: str = "data/embedding_cache"
    # How many files' chunks are pooled into one embed()/Qdrant-upsert
    # call during knowledge indexing (Sprint-N pipeline-optimization
    # pass). Larger batches amortize the fixed per-call overhead of the
    # embedding model and the Qdrant round-trip across many files instead
    # of paying it once per file; bounded so memory stays predictable on
    # the 16GB-RAM consumer-laptop target (ADR-012).
    knowledge_file_batch_size: int = 25

    @property
    def embedding_version(self) -> str:
        """A single string identifying the active embedding configuration.

        Baked into every persisted chunk row and every Redis cache key.
        Changing the provider, model, or dimension changes this string,
        which makes old chunks/cache entries naturally ineligible for
        reuse — the fast-path skip and cache lookups simply stop
        matching, forcing a full re-embed rather than silently mixing
        vectors from two different embedding spaces.

        Returns:
            ``"{provider}:{model}:{dimension}"``.
        """
        if self.embedding_provider == "cloudflare":
            # Pooling is part of the identity: switching it changes the vector space.
            return (
                f"cloudflare:{self.cloudflare_embedding_model}:{self.embedding_dimension}"
                f":{self.cloudflare_embedding_pooling}"
            )
        return f"{self.embedding_provider}:{self.embedding_model}:{self.embedding_dimension}"

    @field_validator("cloudflare_account_id", "cloudflare_api_token", mode="before")
    @classmethod
    def _blank_means_unset(cls, value):
        """Treat ``KEY=`` as "not configured" and trim stray whitespace (``KEY= value`` would corrupt the API URL)."""
        if isinstance(value, str):
            return value.strip() or None
        return value


class LoggingSettings(BaseSettings):
    """Logging behaviour: destinations, format, and rotation."""

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    log_level: Optional[str] = None
    log_format: Literal["json", "text"] = "json"
    log_to_console: bool = True
    log_to_file: bool = True
    log_dir: str = "logs"
    log_file_name: str = "codesage.log"
    log_max_bytes: int = 10_485_760
    log_backup_count: int = 5

    def resolved_level(self, environment: str, debug: bool) -> str:
        """Compute the effective log level.

        Args:
            environment: The active ``AppSettings.environment`` value.
            debug: The active ``AppSettings.debug`` flag.

        Returns:
            An explicit ``LOG_LEVEL`` override if one is set; otherwise
            ``DEBUG`` for local/development runs and ``INFO`` everywhere else.
        """
        if self.log_level:
            return self.log_level.upper()
        return "DEBUG" if debug or environment == "development" else "INFO"


class RetrievalSettings(BaseSettings):
    """Hybrid retrieval tuning (Sprint 4): fusion weights, limits, and cache behavior.

    Weights are configuration, not hard-coded constants, so ranking can
    be tuned (or A/B compared) without a code change. They are not
    required to sum to 1 — they're relative weights in one linear
    fusion formula, not a probability distribution.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    default_top_k: int = 10
    max_top_k: int = 50

    # Per-source candidate caps, applied before fusion — the single
    # biggest lever for "large repository safety" (§11): no source can
    # ever return an unbounded result set, regardless of repository size.
    semantic_candidate_limit: int = 25
    # Cosine similarity from bge-small-en-v1.5 empirically sits ~0.55-0.8
    # for genuinely relevant text and ~0.3-0.5 for unrelated text —
    # vector search always returns its K nearest neighbors regardless of
    # whether any of them are actually relevant, so a floor is required
    # to let "no relevant result" be a real possible outcome rather than
    # always returning the least-bad nearest neighbors.
    semantic_min_score: float = 0.5
    lexical_candidate_limit: int = 25
    lexical_tokens_per_query: int = 6
    structural_max_seeds: int = 10
    structural_max_related_per_seed: int = 5

    # Fusion weights (§4/§6) — deliberately simple, explainable, linear.
    weight_semantic: float = 0.50
    weight_lexical: float = 0.35
    weight_structural: float = 0.15
    entry_point_boost: float = 0.05
    dependency_hotspot_boost: float = 0.05

    lexical_min_similarity: float = 0.2  # pg_trgm similarity() floor

    # Cross-encoder reranking (pre-Sprint-5 hardening pass). Scores the
    # fusion stage's top candidates against the query's actual text
    # relevance (fusion only ever sees cosine/trigram/relationship-type
    # scores, never "does this text actually answer the question").
    # Measured (see docs/SPRINT_LOG.md's hardening section): a real
    # +4.8% MRR improvement, but at 20-30x the query latency (cross-
    # encoder cost scales ~quadratically with sequence length, and code
    # chunks run up to ~3,500 chars) — and Recall@K was already 1.0
    # without it once the test-intent boost (below) was added. Disabled
    # by default: this specific cost/benefit doesn't clear "latency is
    # a first-class design constraint." Left fully implemented and
    # config-toggleable (and overridable per-request via the API's
    # ``rerank`` query param) for deliberate future opt-in — e.g. a
    # slower "deep research" mode is a reasonable place to spend this.
    reranking_enabled: bool = False
    reranking_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    reranking_candidate_pool: int = 10
    reranking_max_chars: int = 800

    # A query containing a testing-intent word (test/tests/testing/spec)
    # boosts candidates whose file matches a generic test-file naming
    # convention — a deterministic, repository-agnostic signal (not
    # tuned to any specific repository's content), addressing the one
    # documented Sprint 4 evaluation gap without overfitting to it.
    test_intent_boost: float = 0.12

    cache_ttl_seconds: int = 300
    cache_enabled: bool = True


class AISettings(BaseSettings):
    """AI Engine pipeline behavior (Sprint 5) — deliberately separate from ``LLMSettings``.

    ``LLMSettings`` owns "how a completion call is made" (provider,
    model, credentials, temperature, timeout). This class owns "how the
    pipeline around that call behaves" (evidence budget, verification
    retries, total latency ceiling, answer caching) — the same split
    ``RetrievalSettings`` already draws from ``QdrantSettings``/
    ``RedisSettings``.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    # Evidence Selection / Context Construction bounds (§4/§5) — "the
    # smallest sufficient set of evidence", never "as much as possible".
    max_evidence_items: int = 8
    max_evidence_per_file: int = 2
    max_context_chars: int = 12_000

    # Verification retry loop (§8/§19) — must have a strict ceiling.
    max_verification_retries: int = 1
    min_evidence_relevance: float = 0.15  # below this, short-circuit to INSUFFICIENT_EVIDENCE before any LLM call

    # Whole-pipeline latency ceiling (§11) — independent of the
    # provider-level timeout in LLMSettings, which bounds one call;
    # this bounds the entire graph, including a verification retry.
    total_timeout_seconds: float = 45.0

    # Answer cache (§12) — a separate Redis key space/TTL from
    # Retrieval's own cache (app/retrieval/cache.py); never conflated.
    answer_cache_enabled: bool = True
    answer_cache_ttl_seconds: int = 1800  # 30 minutes — an LLM answer is more expensive to recompute than a retrieval


class ReportSettings(BaseSettings):
    """Repository Intelligence Reports pipeline behavior (Sprint 6).

    Same split rationale as ``AISettings`` vs. ``LLMSettings``: this
    class owns "how the report pipeline behaves" (whether AI synthesis
    runs at all, report cache lifetime) — the LLM call itself, when
    made, still goes through ``LLMSettings``/``app.ai.llm.provider``
    unchanged (spec §9: reuse the AI Engine, never a second LLM framework).
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    # A whole-repository kill switch for the optional AI-narrative pass
    # (spec §9: "do not make every report require an LLM call if
    # deterministic generation is sufficient" — ``dependency_risk`` and
    # ``health`` never request AI narrative regardless of this flag;
    # this only gates the three report types that do).
    ai_synthesis_enabled: bool = True

    # Report cache (§13) — its own Redis key space/TTL, distinct from
    # both Retrieval's and the AI Engine's caches.
    cache_enabled: bool = True
    cache_ttl_seconds: int = 3600  # 1 hour — a full report is more expensive to recompute than a single AI answer


class IngestionSettings(BaseSettings):
    """File-walk/noise-filtering configuration for the Ingestion module's scanner.

    Kept separate from ``AppSettings`` because these knobs are specific
    to one concern (what the scanner excludes and why) and are tuned
    independently of general app/web settings.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    # Extra directory names to prune, beyond the built-in language/VCS/
    # tooling defaults in ``ingestion/utils.py`` (comma-separated).
    ingestion_extra_ignored_dirs: str = ""
    # Extra exact filenames to exclude (comma-separated) — for
    # project-specific generated files not already covered by the
    # built-in lockfile/minified-bundle list.
    ingestion_extra_ignored_filenames: str = ""
    # Extra filename suffixes to exclude (comma-separated, e.g. ".min.js").
    ingestion_extra_ignored_suffixes: str = ""
    # A cloned repository's own ``.gitignore`` is a strong, repo-specific
    # noise signal (its maintainers already decided what doesn't belong
    # in version control) — respected by default, but can be disabled
    # for repositories with unusual/overly broad ignore rules.
    ingestion_respect_gitignore: bool = True
    # Files larger than this are excluded from the scan entirely (never
    # even recorded as a ``File`` row) — catches large binaries/data
    # files/generated artifacts that aren't on any named-pattern list.
    # Separate from (and larger than) Knowledge's embedding-specific cap,
    # since a large file can still be worth recording as metadata.
    ingestion_max_file_size_bytes: int = 5_000_000

    @property
    def extra_ignored_dirs_list(self) -> list[str]:
        """Parsed, comma-separated extra ignored-directory names."""
        return _split_csv(self.ingestion_extra_ignored_dirs)

    @property
    def extra_ignored_filenames_list(self) -> list[str]:
        """Parsed, comma-separated extra ignored-filename list."""
        return _split_csv(self.ingestion_extra_ignored_filenames)

    @property
    def extra_ignored_suffixes_list(self) -> list[str]:
        """Parsed, comma-separated extra ignored-suffix list."""
        return _split_csv(self.ingestion_extra_ignored_suffixes)


_DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-before-deploying"
_MIN_JWT_SECRET_LENGTH = 32


class AuthSettings(BaseSettings):
    """Authentication, guest access, and abuse-control configuration (ADR-027).

    Quota/limit fields are settings, not constants, so they can be tuned
    per environment without a code change. Integration credentials
    (Turnstile, GitHub OAuth) are optional so local development works
    without them; ``Settings.production_problems`` refuses to start a
    production process that is missing any of them.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    jwt_secret: SecretStr = SecretStr(_DEV_JWT_SECRET)
    jwt_issuer: str = "codesage"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_guest_days: int = 3
    refresh_token_ttl_user_days: int = 30
    # A refresh token presented again within this window of its own
    # rotation is treated as a benign double-submit (e.g. two browser
    # tabs), not theft: rejected, but the token family is NOT revoked.
    refresh_reuse_grace_seconds: int = 10
    guest_ttl_hours: int = 72

    turnstile_secret_key: Optional[SecretStr] = None
    github_client_id: Optional[str] = None
    github_client_secret: Optional[SecretStr] = None
    # The frontend callback URL registered on the GitHub OAuth app; sent
    # again at code-exchange time, where GitHub requires it to match.
    github_redirect_uri: Optional[str] = None
    oauth_state_ttl_seconds: int = 600
    admin_github_logins: str = ""
    # Shared secret for server-to-server endpoints (guest cleanup).
    internal_api_token: Optional[SecretStr] = None
    # How many trusted reverse proxies sit in front of the app. 0 ignores
    # X-Forwarded-For entirely (it is attacker-controlled otherwise); N
    # takes the Nth entry from the END of the header, i.e. the address the
    # outermost trusted proxy recorded. Must be tuned per host at deploy time.
    trusted_proxy_hops: int = 0

    guest_max_repositories: int = 1
    user_max_repositories: int = 5
    guest_daily_questions: int = 15
    user_daily_questions: int = 100
    guest_daily_repository_attempts: int = 3
    guest_creations_per_ip_per_day: int = 5
    guest_global_daily_index_cap: int = 30
    guest_max_repository_files: int = 1500
    guest_max_repository_mb: int = 40

    @field_validator(
        "turnstile_secret_key",
        "github_client_id",
        "github_client_secret",
        "github_redirect_uri",
        "internal_api_token",
        mode="before",
    )
    @classmethod
    def _blank_means_unset(cls, value):
        """Treat ``KEY=`` in a copied ``.env.example`` as "not configured", not as an empty secret."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def _blank_jwt_secret_uses_dev_default(cls, value):
        """A blank ``JWT_SECRET=`` falls back to the dev default (which production refuses to start with)."""
        if isinstance(value, str) and not value.strip():
            return _DEV_JWT_SECRET
        return value

    @property
    def admin_github_logins_list(self) -> list[str]:
        """Parsed, lower-cased admin GitHub logins."""
        return [login.lower() for login in _split_csv(self.admin_github_logins)]

    @property
    def github_oauth_configured(self) -> bool:
        """Whether every GitHub OAuth credential needed for the login flow is present."""
        return bool(self.github_client_id and self.github_client_secret and self.github_redirect_uri)


class Settings:
    """Aggregates every settings group behind a single access point."""

    def __init__(self) -> None:
        self.app = AppSettings()
        self.database = DatabaseSettings()
        self.redis = RedisSettings()
        self.qdrant = QdrantSettings()
        self.llm = LLMSettings()
        self.logging = LoggingSettings()
        self.retrieval = RetrievalSettings()
        self.ai = AISettings()
        self.reports = ReportSettings()
        self.ingestion = IngestionSettings()
        self.celery = CelerySettings()
        self.indexing = IndexingSettings()
        self.auth = AuthSettings()

    def production_problems(self) -> list[str]:
        """List security-relevant misconfigurations that must block a non-development start.

        Applies to ``staging`` as well as ``production``: a staging server
        is still reachable from the internet, so it must not run with the
        publicly known development JWT secret or without bot protection.

        Returns:
            Human-readable problems; empty in development or when the
            configuration is sound.
        """
        if self.app.environment == "development":
            return []
        problems: list[str] = []
        secret = self.auth.jwt_secret.get_secret_value()
        if secret == _DEV_JWT_SECRET or len(secret) < _MIN_JWT_SECRET_LENGTH:
            problems.append(f"JWT_SECRET must be set to a random value of at least {_MIN_JWT_SECRET_LENGTH} characters.")
        if self.auth.turnstile_secret_key is None:
            problems.append("TURNSTILE_SECRET_KEY is required (guest creation must be bot-protected).")
        if not self.auth.github_oauth_configured:
            problems.append("GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET and GITHUB_REDIRECT_URI are required.")
        if self.auth.internal_api_token is None:
            problems.append("INTERNAL_API_TOKEN is required for the guest-cleanup endpoint.")
        if self.app.debug:
            problems.append("DEBUG must be false in production.")
        if self.indexing.indexing_backend == "postgres" and self.app.role == "api" and not self.indexing.indexer_url:
            problems.append("INDEXER_URL is required for ROLE=api with INDEXING_BACKEND=postgres (the API must be able to wake the indexer).")
        if self.app.role == "indexer" and self.indexing.indexing_backend != "postgres":
            problems.append("ROLE=indexer requires INDEXING_BACKEND=postgres.")
        if self.llm.embedding_provider == "cloudflare" and (
            not self.llm.cloudflare_account_id or self.llm.cloudflare_api_token is None
        ):
            problems.append("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN are required when EMBEDDING_PROVIDER=cloudflare.")
        return problems


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    Returns:
        The lazily constructed, cached application settings.
    """
    return Settings()
