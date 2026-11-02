"""Celery tasks for repository indexing (ADR-026).

Lives in ``ingestion/`` (not ``core/``) because these tasks wrap
business logic that already belongs to this module (``run_parsing_pipeline``)
and to the Knowledge module (``run_knowledge_indexing_pipeline``) — the
Celery *app* is infrastructure (``core/celery_app.py``), but a task body
is exactly as much "business logic in a background job" as the
``BackgroundTask`` functions it replaces, so it stays where those lived.

Both tasks:
- Acquire the per-repository Redis lock (``indexing_lock.py``) before
  doing any real work, and always release it in a ``finally`` — this is
  the actual, race-free duplicate-job-prevention guarantee under
  concurrent Celery workers (the API-level 409 check in
  ``WorkspaceService.request_indexing`` remains as a cheap, fast,
  user-facing rejection for the common case, but this lock is what
  makes two simultaneously-dispatched tasks for the same repository
  structurally impossible to both proceed).
- Run the existing async pipeline via ``asyncio.run`` — Celery workers
  (prefork/solo pool) execute task bodies synchronously; each task gets
  its own fresh event loop rather than sharing one across tasks/threads.
- Retry a bounded number of times with backoff on any unhandled
  exception from the pipeline (``CelerySettings.celery_max_retries``),
  via ``self.retry()`` rather than ``autoretry_for`` so the lock release
  in the ``finally`` block always runs first, exactly once, before the
  retry re-enters this same function (and re-acquires the lock) on its
  next attempt.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.db.redis import get_redis_client
from app.ingestion.indexing_lock import acquire_indexing_lock, release_indexing_lock
from app.ingestion.parsing_service import run_parsing_pipeline
from app.knowledge.pipeline import run_knowledge_indexing_pipeline

logger = logging.getLogger("codesage.ingestion.tasks")


async def _run_locked(
    *, repository_id: uuid.UUID, lock_name: str, coro_factory, on_lock_held_skip_message: str,
) -> None:
    """Acquire this repository's indexing lock, run one pipeline coroutine, always release.

    Args:
        repository_id: The repository being (re-)indexed.
        lock_name: A short label for log lines (``"full index"`` / ``"knowledge reindex"``).
        coro_factory: Zero-arg callable returning the coroutine to run once the lock is held.
        on_lock_held_skip_message: Logged (at WARNING) if the lock is already held —
            this is the real, cross-worker duplicate-job-prevention path firing.

    Raises:
        Exception: Whatever the wrapped pipeline raised, so the Celery
            task's own retry logic can react to it. A lock already held
            by another task is *not* an error — it is logged and this
            function returns normally, since the repository is already
            being indexed by whichever task holds the lock.
    """
    settings = get_settings().celery
    redis_client = get_redis_client()
    token = await acquire_indexing_lock(redis_client, repository_id, settings.indexing_lock_ttl_seconds)
    if token is None:
        logger.warning(
            "Skipping %s for repository %s: %s", lock_name, repository_id, on_lock_held_skip_message
        )
        return
    try:
        await coro_factory()
    finally:
        await release_indexing_lock(redis_client, repository_id, token)


_worker_event_loop: asyncio.AbstractEventLoop | None = None


def _get_worker_event_loop() -> asyncio.AbstractEventLoop:
    """Return one persistent event loop, created once per OS process/thread.

    This is the actual fix for a real bug caught live during this pass's
    own concurrency benchmark: ``app.db.postgres``/``app.db.redis``/
    ``app.db.qdrant`` all expose process-wide ``@lru_cache``'d async
    clients (correct and necessary for the ASGI server, which runs one
    event loop for its entire process lifetime) — but a naive
    ``asyncio.run(coro)`` per task call creates a *brand-new* loop and
    tears it down when the task finishes. The cached Postgres engine
    (asyncpg connections are bound to the loop that created them) stays
    bound to whichever loop happened to build it on the *first* task a
    given worker ever ran; every subsequent task in that same
    process/thread then fails with ``RuntimeError: Event loop is
    closed`` / ``'NoneType' object has no attribute 'send'`` trying to
    reuse connections from an already-closed loop. Observed live,
    reproducibly, on the second task run by one worker process.

    Keeping one loop alive for the lifetime of the worker (thread) makes
    the cached clients' lifetime assumption correct again: built once,
    on this loop, on this process/thread's first task, reused by every
    task after it — exactly like the ASGI app.

    Returns:
        The single event loop this process/thread's tasks all run on.
    """
    global _worker_event_loop
    if _worker_event_loop is None or _worker_event_loop.is_closed():
        _worker_event_loop = asyncio.new_event_loop()
    return _worker_event_loop


def _run_async(coro) -> None:
    """Run an async pipeline coroutine from a synchronous Celery task body.

    Uses this process/thread's one persistent loop (see
    :func:`_get_worker_event_loop`) rather than ``asyncio.run()``, which
    would create-and-destroy a fresh loop per call and break the
    process-wide cached async clients after the first task. Safe under
    ``--pool=solo``/``--pool=prefork`` (one event loop per OS process,
    matching those clients' own process-wide caching) — **not** safe
    under ``--pool=threads``/``--pool=eventlet``/``--pool=gevent`` with
    concurrency > 1, since those run several tasks truly concurrently
    within one process, and an asyncio loop (and the cached clients
    bound to it) cannot safely be driven by more than one OS thread.
    Real cross-repository concurrency is achieved via multiple worker
    *processes* instead (Celery's default ``prefork`` pool in Docker;
    several ``--pool=solo`` processes for Windows bare-metal dev) — see
    ``README``/ADR-026 for the exact commands.
    """
    loop = _get_worker_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(coro)


@celery_app.task(bind=True, name="app.ingestion.tasks.run_indexing_task")
def run_indexing_task(self: Task, repository_id: str) -> None:
    """Celery task: full index pipeline (parse -> intelligence -> knowledge) for one repository.

    Args:
        self: The bound task instance (Celery passes this automatically
            with ``bind=True``) — used for ``self.retry()``.
        repository_id: The repository's UUID, as a string (Celery task
            arguments must be JSON-serializable; UUIDs aren't).
    """
    settings = get_settings().celery
    repo_uuid = uuid.UUID(repository_id)

    async def _invoke() -> None:
        await _run_locked(
            repository_id=repo_uuid,
            lock_name="full index",
            coro_factory=lambda: run_parsing_pipeline(repo_uuid),
            on_lock_held_skip_message="another task already holds this repository's indexing lock",
        )

    try:
        _run_async(_invoke())
    except Exception as exc:  # noqa: BLE001 -- convert to a bounded Celery retry
        logger.warning(
            "run_indexing_task failed for repository %s (attempt %d/%d): %s",
            repository_id, self.request.retries + 1, settings.celery_max_retries + 1, exc,
        )
        try:
            raise self.retry(
                exc=exc, max_retries=settings.celery_max_retries,
                countdown=settings.celery_retry_backoff_seconds * (self.request.retries + 1),
            )
        except MaxRetriesExceededError:
            logger.error("run_indexing_task exhausted retries for repository %s", repository_id)
            raise


@celery_app.task(bind=True, name="app.ingestion.tasks.run_knowledge_reindex_task")
def run_knowledge_reindex_task(self: Task, repository_id: str) -> None:
    """Celery task: knowledge-only re-index (chunk/embed/upsert) for one repository.

    Args:
        self: The bound task instance.
        repository_id: The repository's UUID, as a string.
    """
    settings = get_settings().celery
    repo_uuid = uuid.UUID(repository_id)

    async def _invoke() -> None:
        await _run_locked(
            repository_id=repo_uuid,
            lock_name="knowledge reindex",
            coro_factory=lambda: run_knowledge_indexing_pipeline(repo_uuid),
            on_lock_held_skip_message="another task already holds this repository's indexing lock",
        )

    try:
        _run_async(_invoke())
    except Exception as exc:  # noqa: BLE001 -- convert to a bounded Celery retry
        logger.warning(
            "run_knowledge_reindex_task failed for repository %s (attempt %d/%d): %s",
            repository_id, self.request.retries + 1, settings.celery_max_retries + 1, exc,
        )
        try:
            raise self.retry(
                exc=exc, max_retries=settings.celery_max_retries,
                countdown=settings.celery_retry_backoff_seconds * (self.request.retries + 1),
            )
        except MaxRetriesExceededError:
            logger.error("run_knowledge_reindex_task exhausted retries for repository %s", repository_id)
            raise
