"""Tests for the Cloudflare Workers AI embedding provider (ADR-029).

No network: the provider's HTTP client is given an ``httpx.MockTransport``.
Also covers the indexing loop's behaviour when the provider fails for good,
since a swallowed per-batch error would otherwise finish "ready" with every
file failed.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import LLMSettings, Settings
from app.knowledge.embedding import CloudflareEmbeddingProvider
from app.knowledge.exceptions import (
    EmbeddingConfigurationError,
    EmbeddingQuotaExceededError,
    EmbeddingRequestError,
    EmbeddingUnavailableError,
)

TOKEN = "cf-secret-token-value"
DIM = 384


def _settings(**overrides) -> LLMSettings:
    values = dict(
        embedding_provider="cloudflare",
        cloudflare_account_id="acct123",
        cloudflare_api_token=SecretStr(TOKEN),
        cloudflare_embedding_batch_size=3,
        cloudflare_max_retries=2,
        cloudflare_retry_backoff_seconds=1.0,
    )
    values.update(overrides)
    return LLMSettings(**values)


def _ok(texts: list[str], pooling: str = "cls", dim: int = DIM, neurons: str | None = "0.5") -> httpx.Response:
    # Vector i is filled with i so order is checkable.
    data = [[float(i)] * dim for i, _ in enumerate(texts)]
    headers = {"cf-ai-neurons": neurons} if neurons else {}
    return httpx.Response(
        200, json={"success": True, "result": {"shape": [len(texts), dim], "data": data, "pooling": pooling}}, headers=headers
    )


def _error(status: int, code: int, message: str, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json={"success": False, "errors": [{"code": code, "message": message}]}, headers=headers)


class _Recorder:
    """Scripted transport: pops one response (or exception) per request and remembers the requests."""

    def __init__(self, *script) -> None:
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step(json.loads(request.content)["text"]) if callable(step) else step


def _provider(recorder: _Recorder, **overrides):
    sleeps: list[float] = []
    provider = CloudflareEmbeddingProvider(
        _settings(**overrides), client=httpx.Client(transport=httpx.MockTransport(recorder)), sleep=sleeps.append
    )
    return provider, sleeps


class TestRequest:
    def test_sends_cls_pooling_auth_and_texts_to_the_model_url(self):
        recorder = _Recorder(_ok)
        provider, _ = _provider(recorder)

        provider.embed(["a", "b"])

        request = recorder.requests[0]
        assert str(request.url) == "https://api.cloudflare.com/client/v4/accounts/acct123/ai/run/@cf/baai/bge-small-en-v1.5"
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert json.loads(request.content) == {"text": ["a", "b"], "pooling": "cls"}

    def test_splits_into_batches_and_keeps_order(self):
        recorder = _Recorder(_ok)
        provider, _ = _provider(recorder)  # batch size 3

        vectors = provider.embed([str(i) for i in range(7)])

        assert [len(json.loads(r.content)["text"]) for r in recorder.requests] == [3, 3, 1]
        assert len(vectors) == 7 and all(len(v) == DIM for v in vectors)
        # each request numbers its own vectors from 0, so order within a batch is preserved
        assert [v[0] for v in vectors] == [0, 1, 2, 0, 1, 2, 0]

    def test_empty_input_makes_no_request(self):
        recorder = _Recorder(_ok)
        provider, _ = _provider(recorder)
        assert provider.embed([]) == []
        assert recorder.requests == []

    def test_neurons_from_the_response_header_are_accumulated(self):
        provider, _ = _provider(_Recorder(_ok))
        provider.embed(["a"] * 7)  # three requests at 0.5 each
        assert provider.neurons_used == pytest.approx(1.5)

    def test_missing_or_garbage_neuron_header_is_harmless(self):
        provider, _ = _provider(_Recorder(lambda t: _ok(t, neurons="n/a")))
        assert len(provider.embed(["a"])) == 1
        provider, _ = _provider(_Recorder(lambda t: _ok(t, neurons=None)))
        assert len(provider.embed(["a"])) == 1


class TestRetries:
    def test_retries_a_5xx_then_succeeds_with_exponential_backoff(self):
        recorder = _Recorder(httpx.Response(503), httpx.Response(502), _ok)
        provider, sleeps = _provider(recorder)

        assert len(provider.embed(["a"])) == 1
        assert len(recorder.requests) == 3
        assert sleeps == [1.0, 2.0]

    def test_retries_a_network_error(self):
        recorder = _Recorder(httpx.ConnectTimeout("slow"), _ok)
        provider, sleeps = _provider(recorder)
        assert len(provider.embed(["a"])) == 1
        assert sleeps == [1.0]

    def test_429_honours_retry_after_but_caps_it(self):
        recorder = _Recorder(httpx.Response(429, headers={"retry-after": "3"}), httpx.Response(429, headers={"retry-after": "9999"}), _ok)
        provider, sleeps = _provider(recorder)
        provider.embed(["a"])
        assert sleeps == [3.0, 20.0]

    def test_gives_up_with_a_user_safe_message_and_never_leaks_the_token(self):
        recorder = _Recorder(httpx.Response(503))
        provider, _ = _provider(recorder)

        with pytest.raises(EmbeddingUnavailableError) as raised:
            provider.embed(["a"])

        assert len(recorder.requests) == 3  # first try + 2 retries
        assert "files already indexed are kept" in str(raised.value)
        assert TOKEN not in str(raised.value)

    def test_network_failure_message_names_the_error_type_only(self):
        provider, _ = _provider(_Recorder(httpx.ConnectError(f"cannot connect with {TOKEN}")))
        with pytest.raises(EmbeddingUnavailableError) as raised:
            provider.embed(["a"])
        assert TOKEN not in str(raised.value)


class TestNonRetryableFailures:
    @pytest.mark.parametrize(
        "response",
        [
            _error(429, 4006, "you have used up your daily free allocation of 10,000 neurons"),
            _error(400, 9999, "You have used up your Daily Free Allocation"),
        ],
    )
    def test_quota_exhaustion_stops_immediately(self, response):
        recorder = _Recorder(response)
        provider, sleeps = _provider(recorder)

        with pytest.raises(EmbeddingQuotaExceededError) as raised:
            provider.embed(["a"])

        assert len(recorder.requests) == 1 and sleeps == []
        assert "00:00 UTC" in str(raised.value)

    @pytest.mark.parametrize("status", [401, 403])
    def test_rejected_token_is_a_configuration_error_without_retry(self, status):
        recorder = _Recorder(_error(status, 10000, "Authentication error"))
        provider, _ = _provider(recorder)
        with pytest.raises(EmbeddingConfigurationError) as raised:
            provider.embed(["a"])
        assert len(recorder.requests) == 1
        assert TOKEN not in str(raised.value)

    def test_a_rejected_input_is_not_retried_and_is_not_an_abort_error(self):
        recorder = _Recorder(_error(400, 3030, "AiError: invalid input"))
        provider, _ = _provider(recorder)
        with pytest.raises(EmbeddingRequestError):
            provider.embed(["a"])
        assert len(recorder.requests) == 1


class TestResponseValidation:
    def test_wrong_vector_count_is_rejected(self):
        provider, _ = _provider(_Recorder(lambda t: _ok(t + ["extra"])), cloudflare_max_retries=0)
        with pytest.raises(EmbeddingUnavailableError):
            provider.embed(["a"])

    def test_wrong_dimension_is_rejected(self):
        provider, _ = _provider(_Recorder(lambda t: _ok(t, dim=768)), cloudflare_max_retries=0)
        with pytest.raises(EmbeddingUnavailableError):
            provider.embed(["a"])

    def test_unreadable_body_is_rejected(self):
        provider, _ = _provider(_Recorder(httpx.Response(200, text="<html>nope</html>")), cloudflare_max_retries=0)
        with pytest.raises(EmbeddingUnavailableError):
            provider.embed(["a"])

    def test_silent_pooling_fallback_is_caught(self):
        # Mean-pooled vectors would be ~0.95 similar and silently degrade retrieval; never accept them.
        provider, _ = _provider(_Recorder(lambda t: _ok(t, pooling="mean")))
        with pytest.raises(EmbeddingConfigurationError):
            provider.embed(["a"])


class TestConfiguration:
    def test_missing_credentials_fail_clearly(self):
        with pytest.raises(EmbeddingConfigurationError):
            CloudflareEmbeddingProvider(_settings(cloudflare_account_id=None))
        with pytest.raises(EmbeddingConfigurationError):
            CloudflareEmbeddingProvider(_settings(cloudflare_api_token=None))

    def test_blank_env_values_mean_unset(self):
        settings = LLMSettings(cloudflare_account_id="  ", cloudflare_api_token="")
        assert settings.cloudflare_account_id is None and settings.cloudflare_api_token is None

    def test_stray_whitespace_around_values_is_trimmed(self):
        # `CLOUDFLARE_ACCOUNT_ID= abc` (a space after '=') is an easy .env typo that would corrupt the API URL.
        settings = LLMSettings(cloudflare_account_id=" abc ", cloudflare_api_token=" tok ")
        assert settings.cloudflare_account_id == "abc"
        assert settings.cloudflare_api_token.get_secret_value() == "tok"

    def test_embedding_version_separates_providers_and_pooling(self):
        local = LLMSettings(embedding_provider="fastembed").embedding_version
        hosted_cls = _settings().embedding_version
        hosted_mean = _settings(cloudflare_embedding_pooling="mean").embedding_version
        assert len({local, hosted_cls, hosted_mean}) == 3
        assert hosted_cls == "cloudflare:@cf/baai/bge-small-en-v1.5:384:cls"

    def test_batch_size_is_exposed_for_the_indexer(self):
        provider, _ = _provider(_Recorder(_ok), cloudflare_embedding_batch_size=42)
        assert provider.batch_size == 42

    def test_production_refuses_to_start_without_cloudflare_credentials(self):
        settings = Settings()
        settings.app.environment = "production"
        settings.llm = _settings(cloudflare_account_id=None)
        assert any("CLOUDFLARE_ACCOUNT_ID" in problem for problem in settings.production_problems())


class _AbortProvider:
    dimension = 3
    version = "test"
    batch_size = 32

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        raise self.error


class _NoopRedis:
    async def mget(self, keys):
        return [None for _ in keys]


@pytest.fixture()
def indexing(monkeypatch, tmp_path):
    """Wire ``KnowledgeService.index_repository`` to in-memory fakes with 4 files in 4 batches."""
    from app.knowledge import service as service_module

    repository = SimpleNamespace(id=uuid.uuid4(), local_path=str(tmp_path))
    files = []
    for i in range(4):
        (tmp_path / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
        files.append(SimpleNamespace(id=uuid.uuid4(), path=f"m{i}.py", language="Python"))
    state = SimpleNamespace(id=uuid.uuid4(), status="pending", progress=0, error_message=None)

    async def _async(value):
        return value

    kdb, idb = service_module.knowledge_db, service_module.ingestion_db
    monkeypatch.setattr(kdb, "get_index_state", lambda s, r: _async(state))
    monkeypatch.setattr(kdb, "save_index_state", lambda s, st: _async(st))
    monkeypatch.setattr(kdb, "count_chunks", lambda s, r: _async(0))
    monkeypatch.setattr(kdb, "is_file_up_to_date", lambda *a: _async(False))
    monkeypatch.setattr(kdb, "get_chunk_ids_for_files", lambda *a: _async([]))
    monkeypatch.setattr(kdb, "delete_chunks_for_files", lambda *a: _async(None))
    monkeypatch.setattr(kdb, "insert_chunks", lambda *a: _async(None))
    monkeypatch.setattr(service_module.repository_db, "get_by_id", lambda s, r: _async(repository))
    monkeypatch.setattr(idb, "list_files", lambda s, r: _async(files))
    monkeypatch.setattr(idb, "list_symbols_for_repository", lambda s, r: _async([]))
    monkeypatch.setattr(service_module, "get_redis_client", lambda: _NoopRedis())
    monkeypatch.setattr(service_module, "get_qdrant_client", lambda: object())
    settings = service_module.get_settings()
    monkeypatch.setattr(settings.llm, "knowledge_file_batch_size", 1)

    def use(provider):
        monkeypatch.setattr(service_module, "get_embedding_provider", lambda: provider)
        return service_module.KnowledgeService(session=object()), repository, state

    return use


class TestIndexingStopsWhenTheProviderFailsForGood:
    @pytest.mark.parametrize(
        "error",
        [
            EmbeddingQuotaExceededError("quota used up"),
            EmbeddingUnavailableError("service down"),
            EmbeddingConfigurationError("bad token"),
        ],
    )
    async def test_aborts_after_the_first_batch_and_records_the_message(self, indexing, error):
        provider = _AbortProvider(error)
        service, repository, _ = indexing(provider)

        state = await service.index_repository(repository.id)

        assert state.status == "failed"
        assert state.error_message == str(error)
        assert provider.calls == 1  # the other three batches were never attempted

    async def test_a_rejected_input_only_fails_its_own_batch_and_indexing_continues(self, indexing):
        provider = _AbortProvider(EmbeddingRequestError("bad input"))
        service, repository, _ = indexing(provider)

        state = await service.index_repository(repository.id)

        assert provider.calls == 4  # every batch was still attempted
        assert state.status == "ready"
        assert state.total_files_failed == 4
