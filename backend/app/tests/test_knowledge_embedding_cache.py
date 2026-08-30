"""Unit tests for the Redis-backed embedding cache (Sprint 3, Knowledge module).

Uses an in-memory fake Redis client (no real Redis needed) that mimics
only the two calls ``embedding.py`` actually makes: ``mget`` and a
``pipeline().set(...).execute()`` batch write.
"""
from __future__ import annotations

from app.knowledge.embedding import get_cached_embeddings, set_cached_embeddings


class _FakePipeline:
    def __init__(self, store: dict[str, str]) -> None:
        self._store = store
        self._pending: list[tuple[str, str]] = []

    def set(self, key: str, value: str, ex: int | None = None) -> "_FakePipeline":
        self._pending.append((key, value))
        return self

    async def execute(self) -> None:
        for key, value in self._pending:
            self._store[key] = value


class _FakeRedis:
    """In-memory double for ``redis.asyncio.Redis`` covering only what the cache layer calls."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self._store.get(key) for key in keys]

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        return _FakePipeline(self._store)


class _BrokenRedis:
    """Simulates Redis being unreachable — every call raises."""

    async def mget(self, keys: list[str]) -> list[str | None]:
        raise ConnectionError("simulated redis outage")

    def pipeline(self, transaction: bool = False):
        raise ConnectionError("simulated redis outage")


class TestEmbeddingCache:
    async def test_cache_miss_on_empty_cache(self) -> None:
        client = _FakeRedis()
        hits = await get_cached_embeddings(client, "fastembed:v1:384", ["hash-a", "hash-b"])
        assert hits == {}

    async def test_write_then_read_round_trips(self) -> None:
        client = _FakeRedis()
        vectors = {"hash-a": [0.1, 0.2, 0.3], "hash-b": [0.4, 0.5, 0.6]}

        await set_cached_embeddings(client, "fastembed:v1:384", vectors, ttl_seconds=3600)
        hits = await get_cached_embeddings(client, "fastembed:v1:384", ["hash-a", "hash-b", "hash-c"])

        assert hits["hash-a"] == vectors["hash-a"]
        assert hits["hash-b"] == vectors["hash-b"]
        assert "hash-c" not in hits

    async def test_different_embedding_versions_never_collide(self) -> None:
        """Changing the embedding version (model swap) must not return a stale-version vector."""
        client = _FakeRedis()
        await set_cached_embeddings(client, "fastembed:model-a:384", {"hash-a": [1.0, 2.0]}, ttl_seconds=3600)

        hits_same_version = await get_cached_embeddings(client, "fastembed:model-a:384", ["hash-a"])
        hits_new_version = await get_cached_embeddings(client, "fastembed:model-b:384", ["hash-a"])

        assert hits_same_version == {"hash-a": [1.0, 2.0]}
        assert hits_new_version == {}

    async def test_redis_outage_on_read_is_a_miss_not_an_error(self) -> None:
        hits = await get_cached_embeddings(_BrokenRedis(), "v1", ["hash-a"])
        assert hits == {}

    async def test_redis_outage_on_write_does_not_raise(self) -> None:
        # Must not raise — a cache-write failure is non-fatal by design.
        await set_cached_embeddings(_BrokenRedis(), "v1", {"hash-a": [1.0]}, ttl_seconds=60)

    async def test_empty_inputs_are_no_ops(self) -> None:
        client = _FakeRedis()
        assert await get_cached_embeddings(client, "v1", []) == {}
        await set_cached_embeddings(client, "v1", {}, ttl_seconds=60)
        assert client._store == {}
