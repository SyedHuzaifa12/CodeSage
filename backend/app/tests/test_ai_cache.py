"""Unit tests for the AI answer cache — key correctness and round-tripping (Sprint 5)."""
from __future__ import annotations

import uuid

from app.ai.cache import build_cache_key, get_cached_answer, set_cached_answer
from app.ai.schemas.dto import AskMetadata, AskResponseData, StageLatency, VerificationInfo
from app.core.config import Settings

REPO_A = uuid.uuid4()
REPO_B = uuid.uuid4()


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value


def make_response(repository_id: uuid.UUID) -> AskResponseData:
    return AskResponseData(
        repository_id=repository_id, query="q", answer="answer text", explanation=None, evidence=[],
        relevant_files=[], relevant_symbols=[],
        verification=VerificationInfo(status="supported", reasons=[]),
        metadata=AskMetadata(
            intent="general", provider="groq", model="llama-3.3-70b-versatile", cache_hit=False, retry_count=0,
            stage_latency_ms=StageLatency(), retrieval_candidates=0,
        ),
    )


class TestBuildCacheKey:
    def _base_kwargs(self, repository_id: uuid.UUID) -> dict:
        return dict(
            repository_id=repository_id, normalized_query="find auth", top_k=10, sources=None,
            corpus_version="v1", llm_settings=Settings().llm,
        )

    def test_same_inputs_produce_same_key(self) -> None:
        kwargs = self._base_kwargs(REPO_A)
        assert build_cache_key(**kwargs) == build_cache_key(**kwargs)

    def test_different_repository_never_collides(self) -> None:
        key_a = build_cache_key(**self._base_kwargs(REPO_A))
        key_b = build_cache_key(**self._base_kwargs(REPO_B))
        assert key_a != key_b
        assert str(REPO_A) in key_a
        assert str(REPO_B) in key_b

    def test_different_provider_produces_different_key(self) -> None:
        kwargs = self._base_kwargs(REPO_A)
        groq_settings = Settings().llm
        groq_settings.llm_provider = "groq"
        ollama_settings = Settings().llm
        ollama_settings.llm_provider = "ollama"
        key_groq = build_cache_key(**{**kwargs, "llm_settings": groq_settings})
        key_ollama = build_cache_key(**{**kwargs, "llm_settings": ollama_settings})
        assert key_groq != key_ollama

    def test_different_model_produces_different_key(self) -> None:
        kwargs = self._base_kwargs(REPO_A)
        settings_a = Settings().llm
        settings_a.groq_model = "model-a"
        settings_b = Settings().llm
        settings_b.groq_model = "model-b"
        assert build_cache_key(**{**kwargs, "llm_settings": settings_a}) != build_cache_key(**{**kwargs, "llm_settings": settings_b})

    def test_different_corpus_version_produces_different_key(self) -> None:
        kwargs = self._base_kwargs(REPO_A)
        key_v1 = build_cache_key(**{**kwargs, "corpus_version": "v1"})
        key_v2 = build_cache_key(**{**kwargs, "corpus_version": "v2"})
        assert key_v1 != key_v2


class TestAnswerCacheRoundTrip:
    async def test_write_then_read_round_trips(self) -> None:
        client = _FakeRedis()
        original = make_response(REPO_A)
        await set_cached_answer(client, "key-a", original, ttl_seconds=1800)
        restored = await get_cached_answer(client, "key-a")
        assert restored == original

    async def test_miss_on_empty_cache(self) -> None:
        assert await get_cached_answer(_FakeRedis(), "missing-key") is None

    async def test_corrupt_entry_is_treated_as_a_miss(self) -> None:
        client = _FakeRedis()
        client._store["key-a"] = "not valid json"
        assert await get_cached_answer(client, "key-a") is None

    async def test_redis_outage_is_a_miss_not_an_error(self) -> None:
        class _BrokenRedis:
            async def get(self, key: str):
                raise ConnectionError("simulated outage")

        assert await get_cached_answer(_BrokenRedis(), "key-a") is None

    async def test_redis_outage_on_write_does_not_raise(self) -> None:
        class _BrokenRedis:
            async def set(self, key: str, value: str, ex=None):
                raise ConnectionError("simulated outage")

        await set_cached_answer(_BrokenRedis(), "key-a", make_response(REPO_A), ttl_seconds=1800)
