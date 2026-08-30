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

from pydantic import SecretStr
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
    embedding_provider: Literal["fastembed"] = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimension: int = 384
    embedding_batch_size: int = 32
    embedding_cache_ttl_seconds: int = 2_592_000  # 30 days — Redis is a pure perf cache, never the source of truth
    embedding_model_cache_dir: str = "data/embedding_cache"

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
        return f"{self.embedding_provider}:{self.embedding_model}:{self.embedding_dimension}"


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


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    Returns:
        The lazily constructed, cached application settings.
    """
    return Settings()
