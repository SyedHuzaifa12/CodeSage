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
    """LLM provider configuration (Groq primary, Ollama fallback — ADR-014).

    Configuration only: no LLM or embedding calls are made in this sprint.
    These values are consumed once the AI module is implemented.
    """

    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore", case_sensitive=False)

    llm_provider: Literal["groq", "ollama"] = "groq"
    groq_api_key: Optional[SecretStr] = None
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    embedding_model: str = "BAAI/bge-small-en-v1.5"


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


class Settings:
    """Aggregates every settings group behind a single access point."""

    def __init__(self) -> None:
        self.app = AppSettings()
        self.database = DatabaseSettings()
        self.redis = RedisSettings()
        self.qdrant = QdrantSettings()
        self.llm = LLMSettings()
        self.logging = LoggingSettings()


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance.

    Returns:
        The lazily constructed, cached application settings.
    """
    return Settings()
