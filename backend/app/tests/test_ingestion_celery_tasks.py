"""Unit tests for the Celery task wrappers (ADR-026).

Exercises ``app.ingestion.tasks`` with the real lock module (against the
real Redis used by ``test_ingestion_indexing_lock.py``) but a fake
pipeline coroutine, in Celery's own ``task_always_eager`` mode — this
runs the task body synchronously in-process (no real worker/broker
needed) while still exercising the actual ``self.retry()``/lock-acquire/
lock-release code path, not a reimplementation of it.

Each task invocation creates its own fresh event loop internally
(``app.ingestion.tasks._run_async`` -> ``asyncio.run(...)``, mirroring
how a real Celery worker process executes a task body), so every Redis
client used *inside* a task is constructed fresh per call rather than
shared across test/task event loops — sharing one ``redis.asyncio``
client across different event loops raises "Future attached to a
different loop" errors. Verification *outside* a task call uses a plain
synchronous ``redis`` client instead, which has no event-loop affinity.
"""
from __future__ import annotations

import os
import uuid

import pytest
import redis as sync_redis
import redis.asyncio as redis

from celery.exceptions import Retry

from app.core.celery_app import celery_app
from app.ingestion import tasks as tasks_module
from app.ingestion.indexing_lock import lock_key_for

_REDIS_HOST = os.environ.get("TEST_REDIS_HOST", "localhost")
_REDIS_PORT = int(os.environ.get("TEST_REDIS_PORT", "6380"))
_TEST_DB = 15


def _redis_reachable() -> bool:
    try:
        client = sync_redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, db=_TEST_DB, socket_connect_timeout=2)
        return bool(client.ping())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_reachable(), reason=f"No reachable Redis at {_REDIS_HOST}:{_REDIS_PORT} for this test"
)


@pytest.fixture(autouse=True)
def _eager_celery():
    """Run tasks synchronously, in-process — no broker/worker required."""
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


@pytest.fixture()
def sync_client():
    """A plain synchronous client for state verification between/after task calls."""
    client = sync_redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, db=_TEST_DB, decode_responses=True)
    yield client
    client.flushdb()
    client.close()


def _fresh_async_client() -> redis.Redis:
    """Build a brand-new async client — called from inside a task's own event loop."""
    return redis.Redis(host=_REDIS_HOST, port=_REDIS_PORT, db=_TEST_DB, decode_responses=True)


class TestRunIndexingTask:
    def test_successful_run_releases_the_lock(self, monkeypatch: pytest.MonkeyPatch, sync_client):
        repository_id = uuid.uuid4()
        calls: list[uuid.UUID] = []

        async def _fake_pipeline(repo_id):
            calls.append(repo_id)

        monkeypatch.setattr(tasks_module, "run_parsing_pipeline", _fake_pipeline)
        monkeypatch.setattr(tasks_module, "get_redis_client", _fresh_async_client)

        tasks_module.run_indexing_task.apply(args=[str(repository_id)]).get()

        assert calls == [repository_id]
        assert sync_client.get(lock_key_for(repository_id)) is None, "lock must be released after a successful run"

    def test_failure_is_not_swallowed_and_requests_a_retry(self, monkeypatch: pytest.MonkeyPatch, sync_client):
        """A pipeline failure must (a) not be silently swallowed — it
        surfaces as Celery's own ``Retry`` signal, which is what makes the
        worker re-enqueue the task — and (b) still release the lock, so
        the eventual retry (or a different worker, per the real
        duplicate-prevention test) isn't permanently blocked by a lock
        orphaned by the failed attempt."""
        repository_id = uuid.uuid4()
        attempts = {"count": 0}

        async def _always_fails(repo_id):
            attempts["count"] += 1
            raise RuntimeError("simulated pipeline crash")

        monkeypatch.setattr(tasks_module, "run_parsing_pipeline", _always_fails)
        monkeypatch.setattr(tasks_module, "get_redis_client", _fresh_async_client)

        settings = tasks_module.get_settings().celery
        monkeypatch.setattr(settings, "celery_max_retries", 2)
        monkeypatch.setattr(settings, "celery_retry_backoff_seconds", 0)

        # `.apply()`'s eager simulation does not itself loop the retry
        # the way a real worker's `apply_async` chain would — it signals
        # intent to retry by raising Celery's own `Retry`, exactly like a
        # real worker does internally before re-enqueuing. Asserting on
        # that signal (rather than reimplementing the worker's retry
        # loop here) tests this task's own obligation — catch, release
        # the lock, call ``self.retry()`` — without re-testing Celery's
        # already-tested retry-counting machinery.
        with pytest.raises(Retry):
            tasks_module.run_indexing_task.apply(args=[str(repository_id)]).get()

        assert attempts["count"] == 1
        assert sync_client.get(lock_key_for(repository_id)) is None, "lock must not leak after a failed attempt"

    def test_lock_already_held_is_skipped_not_run(self, monkeypatch: pytest.MonkeyPatch, sync_client):
        """A second task for a repository whose lock is already held (another
        worker's task in flight) must not touch the repository at all."""
        repository_id = uuid.uuid4()
        calls: list[uuid.UUID] = []

        async def _fake_pipeline(repo_id):
            calls.append(repo_id)

        monkeypatch.setattr(tasks_module, "run_parsing_pipeline", _fake_pipeline)
        monkeypatch.setattr(tasks_module, "get_redis_client", _fresh_async_client)

        sync_client.set(lock_key_for(repository_id), "some-other-task-token", nx=True, ex=30)

        tasks_module.run_indexing_task.apply(args=[str(repository_id)]).get()

        assert calls == [], "pipeline must never run while another task holds the lock"
        # The other task's lock must be left completely untouched.
        assert sync_client.get(lock_key_for(repository_id)) == "some-other-task-token"
