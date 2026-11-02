"""Tests for the cross-worker indexing lock (ADR-026).

Uses a **real** Redis instance (not a fake) and real concurrent
``asyncio`` tasks racing to acquire the same repository's lock — this is
the genuine concurrency test the Celery pass specifically requires
("concurrent Celery tasks can't corrupt a repository's index" / "not
just the single-process guard"), since two independent Celery worker
*processes* would, in practice, each be making exactly these same Redis
calls concurrently; the inter-process race this guards against is fully
exercised by concurrent asyncio tasks against one real Redis server —
the serialization guarantee comes from Redis's own atomicity, not from
anything about the caller being single-process.

Skipped entirely if no Redis is reachable (e.g. a CI box with no
``docker compose up`` run) rather than failing the whole suite.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import redis.asyncio as redis

from app.ingestion.indexing_lock import acquire_indexing_lock, lock_key_for, release_indexing_lock

_REDIS_HOST = os.environ.get("TEST_REDIS_HOST", "localhost")
_REDIS_PORT = int(os.environ.get("TEST_REDIS_PORT", "6380"))  # codesage-redis's published host port


async def _make_client() -> redis.Redis:
    client = redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, db=15, decode_responses=True)
    try:
        await client.ping()
    except Exception:
        pytest.skip(f"No reachable Redis at {_REDIS_HOST}:{_REDIS_PORT} for the real-concurrency lock test")
    return client


@pytest.fixture()
async def redis_client():
    client = await _make_client()
    yield client
    await client.flushdb()
    await client.aclose()


class TestIndexingLockRealConcurrency:
    async def test_only_one_of_many_concurrent_acquires_wins(self, redis_client: redis.Redis):
        """The actual guarantee Celery concurrency depends on: simultaneous
        acquire attempts for the same repository_id, racing for real
        against one Redis server, must let exactly one through."""
        repository_id = uuid.uuid4()

        results = await asyncio.gather(
            *[acquire_indexing_lock(redis_client, repository_id, ttl_seconds=30) for _ in range(20)]
        )

        winners = [token for token in results if token is not None]
        assert len(winners) == 1, f"expected exactly one winner, got {len(winners)}: {winners}"

    async def test_independent_repositories_never_contend(self, redis_client: redis.Redis):
        repo_a, repo_b = uuid.uuid4(), uuid.uuid4()

        token_a, token_b = await asyncio.gather(
            acquire_indexing_lock(redis_client, repo_a, ttl_seconds=30),
            acquire_indexing_lock(redis_client, repo_b, ttl_seconds=30),
        )

        assert token_a is not None
        assert token_b is not None

    async def test_release_then_reacquire_succeeds(self, redis_client: redis.Redis):
        repository_id = uuid.uuid4()

        token = await acquire_indexing_lock(redis_client, repository_id, ttl_seconds=30)
        assert token is not None

        released = await release_indexing_lock(redis_client, repository_id, token)
        assert released is True

        second_token = await acquire_indexing_lock(redis_client, repository_id, ttl_seconds=30)
        assert second_token is not None

    async def test_release_with_stale_token_is_a_safe_no_op(self, redis_client: redis.Redis):
        """A lock that expired and was re-acquired by someone else must
        never be released by a caller presenting its old, no-longer-valid token
        (the exact corruption/duplicate-vector scenario this lock exists to prevent)."""
        repository_id = uuid.uuid4()

        first_token = await acquire_indexing_lock(redis_client, repository_id, ttl_seconds=30)
        assert first_token is not None
        # Simulate the first lock's TTL expiring and a second task taking over.
        await redis_client.delete(lock_key_for(repository_id))
        second_token = await acquire_indexing_lock(redis_client, repository_id, ttl_seconds=30)
        assert second_token is not None
        assert second_token != first_token

        released = await release_indexing_lock(redis_client, repository_id, first_token)
        assert released is False  # must NOT have torn down the second task's still-active lock

        still_held = await redis_client.get(lock_key_for(repository_id))
        assert still_held == second_token

    async def test_a_second_task_sees_the_lock_held_and_skips(self, redis_client: redis.Redis):
        repository_id = uuid.uuid4()

        first = await acquire_indexing_lock(redis_client, repository_id, ttl_seconds=30)
        second = await acquire_indexing_lock(redis_client, repository_id, ttl_seconds=30)

        assert first is not None
        assert second is None
