"""Tests for hosted-deployment configuration (Phase 6, ADR-030): provider URLs, TLS, Qdrant Cloud,
and the guards that refuse to start an internet-facing process with an unsafe config.

No infrastructure needed.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from pydantic import SecretStr
from sqlalchemy.engine import make_url

from app.core.config import DatabaseSettings, QdrantSettings, RedisSettings, Settings
from app.db.dsn import prepare_asyncpg_dsn

# What Neon actually shows (pooled endpoint), including the parameter asyncpg rejects.
NEON_POOLED = (
    "postgresql://neondb_owner:npg_Ab12@ep-cool-name-123456-pooler.eu-central-1.aws.neon.tech/neondb"
    "?sslmode=require&channel_binding=require"
)
NEON_DIRECT = NEON_POOLED.replace("-pooler", "")


class TestPrepareAsyncpgDsn:
    def test_a_neon_pooled_url_becomes_something_asyncpg_accepts(self):
        prepared = prepare_asyncpg_dsn(NEON_POOLED)
        url = make_url(prepared.url)

        assert url.drivername == "postgresql+asyncpg"
        assert url.host == "ep-cool-name-123456-pooler.eu-central-1.aws.neon.tech" and url.database == "neondb"
        assert dict(url.query) == {}  # sslmode and channel_binding must not reach asyncpg as query arguments
        assert prepared.connect_args["ssl"] == "require"
        assert "channel_binding" not in prepared.url and "sslmode" not in prepared.url

    def test_a_pooled_endpoint_turns_prepared_statements_off(self):
        prepared = prepare_asyncpg_dsn(NEON_POOLED)
        assert prepared.pooled is True
        assert prepared.connect_args["statement_cache_size"] == 0
        assert prepared.connect_args["prepared_statement_cache_size"] == 0
        # PgBouncer hands each statement to a different server connection: names must never collide.
        assert prepared.connect_args["prepared_statement_name_func"]() != prepared.connect_args["prepared_statement_name_func"]()

    def test_a_direct_endpoint_keeps_normal_statement_caching(self):
        prepared = prepare_asyncpg_dsn(NEON_DIRECT)
        assert prepared.pooled is False
        assert set(prepared.connect_args) == {"ssl"}

    @pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
    def test_all_the_usual_schemes_are_accepted(self, scheme):
        prepared = prepare_asyncpg_dsn(f"{scheme}://u:p@db.example.com:5432/app")
        assert prepared.url.startswith("postgresql+asyncpg://")

    @pytest.mark.parametrize("raw", ["mysql://u:p@h/db", "redis://h:6379/0"])
    def test_other_databases_are_refused(self, raw):
        with pytest.raises(ValueError, match="PostgreSQL"):
            prepare_asyncpg_dsn(raw)

    def test_a_url_without_a_host_is_refused(self):
        with pytest.raises(ValueError, match="host"):
            prepare_asyncpg_dsn("postgresql:///dbonly")

    def test_a_malformed_url_is_refused_without_echoing_the_password(self):
        with pytest.raises(ValueError) as raised:
            prepare_asyncpg_dsn("not a url but has hunter2 in it")
        assert "hunter2" not in str(raised.value)

    def test_special_characters_in_the_password_survive_the_round_trip(self):
        prepared = prepare_asyncpg_dsn("postgresql://user:p%40ss%2Fw%25rd%3F@db.example.com/app")
        assert make_url(prepared.url).password == "p@ss/w%rd?"

    def test_sslmode_disable_means_no_tls(self):
        assert prepare_asyncpg_dsn("postgresql://u:p@h/db?sslmode=disable").connect_args["ssl"] is False

    def test_an_unknown_sslmode_is_refused(self):
        with pytest.raises(ValueError, match="sslmode"):
            prepare_asyncpg_dsn("postgresql://u:p@h/db?sslmode=banana")

    def test_the_fallback_sslmode_applies_only_when_the_url_has_none(self):
        assert prepare_asyncpg_dsn("postgresql://u:p@h/db", sslmode="require").connect_args["ssl"] == "require"
        assert prepare_asyncpg_dsn("postgresql://u:p@h/db?sslmode=verify-full", sslmode="require").connect_args["ssl"] == "verify-full"

    def test_a_plain_local_url_is_untouched(self):
        prepared = prepare_asyncpg_dsn("postgresql://codesage:codesage@localhost:5432/codesage")
        assert prepared.connect_args == {} and prepared.pooled is False


class TestDatabaseSettings:
    def _settings(self, **kw) -> DatabaseSettings:
        base = dict(postgres_host="h", postgres_port=5432, postgres_user="u", postgres_password=SecretStr("pw"), postgres_db="d")
        base.update(kw)
        return DatabaseSettings(**base)

    def test_discrete_fields_still_work_and_quote_awkward_passwords(self):
        # Before this phase an '@' in the password silently broke the URL.
        prepared = self._settings(postgres_password=SecretStr("p@ss/word")).prepared()
        assert make_url(prepared.url).password == "p@ss/word" and make_url(prepared.url).host == "h"

    def test_discrete_mode_can_require_tls(self):
        assert self._settings(postgres_sslmode="require").prepared().connect_args["ssl"] == "require"

    def test_database_url_wins_over_the_discrete_fields(self):
        prepared = self._settings(database_url=SecretStr(NEON_POOLED)).prepared()
        assert make_url(prepared.url).host.endswith("neon.tech")

    def test_migrations_use_the_direct_url_when_one_is_given_otherwise_the_main_one(self):
        both = self._settings(database_url=SecretStr(NEON_POOLED), migration_database_url=SecretStr(NEON_DIRECT))
        assert both.prepared().pooled is True
        assert both.prepared(migration=True).pooled is False  # DDL must not go through the transaction pooler

        only_main = self._settings(database_url=SecretStr(NEON_POOLED))
        assert only_main.prepared(migration=True).pooled is True

    def test_blank_values_mean_unset(self):
        settings = DatabaseSettings(database_url="  ", migration_database_url="", postgres_sslmode="")
        assert settings.database_url is None and settings.migration_database_url is None and settings.postgres_sslmode is None

    def test_async_dsn_is_kept_for_existing_callers(self):
        assert self._settings().async_dsn.startswith("postgresql+asyncpg://u:pw@h:5432/d")


class TestEngineConstruction:
    def test_the_engine_gets_the_driver_arguments_and_pool_settings(self, monkeypatch):
        import app.db.postgres as postgres
        from app.core.config import get_settings

        captured = {}
        monkeypatch.setattr(postgres, "create_async_engine", lambda url, **kw: captured.update(url=url, **kw) or object())
        database = get_settings().database
        monkeypatch.setattr(database, "database_url", SecretStr(NEON_POOLED))
        monkeypatch.setattr(database, "postgres_pool_size", 3)
        postgres.get_engine.cache_clear()
        try:
            postgres.get_engine()
        finally:
            postgres.get_engine.cache_clear()

        assert captured["connect_args"]["ssl"] == "require" and captured["connect_args"]["statement_cache_size"] == 0
        assert captured["pool_size"] == 3 and captured["pool_pre_ping"] is True
        assert captured["pool_recycle"] == 240  # below Neon's 5-minute scale-to-zero
        assert "channel_binding" not in captured["url"]


class TestAlembicWithAHostedUrl:
    def test_migrations_accept_a_url_whose_password_contains_percent_escapes(self):
        # ConfigParser treats '%' as interpolation syntax; an unescaped URL-encoded password makes alembic crash.
        env = {
            **os.environ,
            "MIGRATION_DATABASE_URL": "postgresql://u:p%40ss%2Fw@ep-x.eu-central-1.aws.neon.tech/db?sslmode=require&channel_binding=require",
        }
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
            capture_output=True, text=True, timeout=120, env=env,
        )
        assert result.returncode == 0, result.stderr[-600:]
        assert "CREATE TABLE indexing_jobs" in result.stdout


class TestRedisClient:
    def _client(self, monkeypatch, **cfg):
        import app.db.redis as redis_module
        from app.core.config import get_settings

        for key, value in cfg.items():
            monkeypatch.setattr(get_settings().redis, key, value)
        redis_module.get_redis_client.cache_clear()
        try:
            return redis_module.get_redis_client()
        finally:
            redis_module.get_redis_client.cache_clear()

    def test_plain_by_default_so_local_compose_is_unchanged(self, monkeypatch):
        client = self._client(monkeypatch, redis_ssl=False)
        assert client.connection_pool.connection_class.__name__ == "Connection"

    def test_tls_verifies_both_the_certificate_and_the_hostname(self, monkeypatch):
        client = self._client(monkeypatch, redis_ssl=True, redis_ssl_ca_certs="/etc/ca.pem")
        kwargs = client.connection_pool.connection_kwargs
        assert client.connection_pool.connection_class.__name__ == "SSLConnection"
        assert kwargs["ssl_cert_reqs"] == "required" and kwargs["ssl_check_hostname"] is True
        assert kwargs["ssl_ca_certs"] == "/etc/ca.pem"

    def test_blank_ca_path_means_system_cas(self):
        assert RedisSettings(redis_ssl_ca_certs="  ").redis_ssl_ca_certs is None

    def test_celery_broker_url_uses_tls_when_redis_does(self, monkeypatch):
        from app.core import celery_app
        from app.core.config import get_settings

        monkeypatch.setattr(get_settings().redis, "redis_ssl", True)
        assert celery_app._build_redis_url(1).startswith("rediss://") and "ssl_cert_reqs=required" in celery_app._build_redis_url(1)


class TestQdrantClient:
    def _client(self, monkeypatch, **cfg):
        import app.db.qdrant as qdrant_module
        from app.core.config import get_settings

        for key, value in cfg.items():
            monkeypatch.setattr(get_settings().qdrant, key, value)
        qdrant_module.get_qdrant_client.cache_clear()
        try:
            return qdrant_module.get_qdrant_client()
        finally:
            qdrant_module.get_qdrant_client.cache_clear()

    @pytest.mark.parametrize("url", ["https://abc.eu-central-1-0.aws.cloud.qdrant.io:6333", "https://abc.eu-central-1-0.aws.cloud.qdrant.io"])
    def test_cloud_url_and_api_key_are_used_with_or_without_the_port(self, monkeypatch, url):
        client = self._client(monkeypatch, qdrant_url=url, qdrant_api_key=SecretStr("k-123"))
        remote = client._client
        assert remote.rest_uri == "https://abc.eu-central-1-0.aws.cloud.qdrant.io:6333"
        assert remote._rest_headers.get("api-key") == "k-123"

    def test_local_default_is_unchanged(self, monkeypatch):
        client = self._client(monkeypatch, qdrant_url=None, qdrant_api_key=None)
        assert client._client.rest_uri == "http://localhost:6333"
        assert "api-key" not in client._client._rest_headers

    def test_building_the_client_does_not_make_a_network_call(self, monkeypatch):
        # The version probe is blocking I/O; an unreachable URL must not delay or fail construction.
        client = self._client(monkeypatch, qdrant_url="https://nothing.invalid", qdrant_api_key=SecretStr("k"))
        assert client is not None

    def test_a_url_needs_a_scheme_and_loses_trailing_slashes(self):
        with pytest.raises(ValueError, match="http"):
            QdrantSettings(qdrant_url="abc.cloud.qdrant.io")
        assert QdrantSettings(qdrant_url=" https://abc.cloud.qdrant.io:6333/ ").qdrant_url == "https://abc.cloud.qdrant.io:6333"
        assert QdrantSettings(qdrant_url="", qdrant_api_key="").qdrant_url is None


class TestProductionGuards:
    def _healthy_hosted(self, monkeypatch) -> Settings:
        settings = Settings()
        monkeypatch.setattr(settings.app, "environment", "production")
        monkeypatch.setattr(settings.app, "debug", False)
        monkeypatch.setattr(settings.app, "allowed_hosts", "api.onrender.com,*.onrender.com")
        monkeypatch.setattr(settings.app, "cors_origins", "https://codesage.netlify.app")
        monkeypatch.setattr(settings.database, "database_url", SecretStr(NEON_POOLED))
        monkeypatch.setattr(settings.llm, "embedding_provider", "cloudflare")
        monkeypatch.setattr(settings.llm, "cloudflare_account_id", "acct")
        monkeypatch.setattr(settings.llm, "cloudflare_api_token", SecretStr("tok"))
        monkeypatch.setattr(settings.auth, "jwt_secret", SecretStr("x" * 40))
        monkeypatch.setattr(settings.auth, "turnstile_secret_key", SecretStr("t"))
        monkeypatch.setattr(settings.auth, "github_client_id", "id")
        monkeypatch.setattr(settings.auth, "github_client_secret", SecretStr("s"))
        monkeypatch.setattr(settings.auth, "github_redirect_uri", "https://codesage.netlify.app/auth/callback")
        monkeypatch.setattr(settings.auth, "internal_api_token", SecretStr("i" * 20))
        return settings

    def test_a_correct_hosted_configuration_has_no_problems(self, monkeypatch):
        assert self._healthy_hosted(monkeypatch).production_problems() == []

    def test_wildcard_hosts_are_refused(self, monkeypatch):
        settings = self._healthy_hosted(monkeypatch)
        monkeypatch.setattr(settings.app, "allowed_hosts", "*")
        assert any("ALLOWED_HOSTS" in p for p in settings.production_problems())

    def test_wildcard_cors_is_refused(self, monkeypatch):
        settings = self._healthy_hosted(monkeypatch)
        monkeypatch.setattr(settings.app, "cors_origins", "https://a.example,*")
        assert any("CORS_ORIGINS" in p for p in settings.production_problems())

    def test_the_public_default_database_password_is_refused(self, monkeypatch):
        settings = self._healthy_hosted(monkeypatch)
        monkeypatch.setattr(settings.database, "database_url", None)
        assert any("DATABASE_URL" in p for p in settings.production_problems())

    def test_an_unusable_database_url_is_reported_without_leaking_it(self, monkeypatch):
        settings = self._healthy_hosted(monkeypatch)
        monkeypatch.setattr(settings.database, "database_url", SecretStr("mysql://u:hunter2@h/db"))
        problems = " ".join(settings.production_problems())
        assert "PostgreSQL" in problems and "hunter2" not in problems

    def test_the_local_model_provider_without_the_library_is_refused(self, monkeypatch):
        import importlib.util

        settings = self._healthy_hosted(monkeypatch)
        monkeypatch.setattr(settings.llm, "embedding_provider", "fastembed")
        monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: None if name == "fastembed" else object())
        assert any("fastembed is not installed" in p for p in settings.production_problems())

    def test_the_indexer_needs_none_of_the_user_facing_secrets(self, monkeypatch):
        settings = self._healthy_hosted(monkeypatch)
        monkeypatch.setattr(settings.app, "role", "indexer")
        monkeypatch.setattr(settings.indexing, "indexing_backend", "postgres")
        monkeypatch.setattr(settings.auth, "jwt_secret", SecretStr("change-me"))  # unset: the dev default
        monkeypatch.setattr(settings.auth, "turnstile_secret_key", None)
        monkeypatch.setattr(settings.auth, "github_client_id", None)
        monkeypatch.setattr(settings.app, "cors_origins", "*")  # irrelevant: it serves no browsers
        assert settings.production_problems() == []

    def test_the_indexer_still_needs_the_shared_internal_token_and_a_real_host_list(self, monkeypatch):
        settings = self._healthy_hosted(monkeypatch)
        monkeypatch.setattr(settings.app, "role", "indexer")
        monkeypatch.setattr(settings.indexing, "indexing_backend", "postgres")
        monkeypatch.setattr(settings.auth, "internal_api_token", None)
        monkeypatch.setattr(settings.app, "allowed_hosts", "*")
        problems = " ".join(settings.production_problems())
        assert "INTERNAL_API_TOKEN" in problems and "ALLOWED_HOSTS" in problems

    @pytest.mark.parametrize("role", ["api", "all"])
    def test_user_facing_roles_still_need_all_of_them(self, monkeypatch, role):
        settings = self._healthy_hosted(monkeypatch)
        monkeypatch.setattr(settings.app, "role", role)
        monkeypatch.setattr(settings.indexing, "indexer_url", "https://i.example")
        monkeypatch.setattr(settings.auth, "turnstile_secret_key", None)
        monkeypatch.setattr(settings.auth, "github_client_id", None)
        monkeypatch.setattr(settings.app, "cors_origins", "*")
        problems = " ".join(settings.production_problems())
        assert "TURNSTILE_SECRET_KEY" in problems and "GITHUB_CLIENT_ID" in problems and "CORS_ORIGINS" in problems

    def test_none_of_this_applies_to_local_development(self):
        settings = Settings()
        assert settings.app.environment == "development" and settings.production_problems() == []
