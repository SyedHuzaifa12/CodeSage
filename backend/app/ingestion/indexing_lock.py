"""Cross-worker indexing lock (ADR-026) — real duplicate-job prevention under Celery.

The pre-Celery guard (``WorkspaceService.request_indexing`` rejecting a
second trigger while ``Repository.indexing_status == "indexing"``) is a
correct, cheap *first* line of defense for the common case (a user
re-clicking "index"), but it has a real TOCTOU race once indexing can be
dispatched from multiple API processes to multiple Celery workers: two
concurrent ``POST /index`` requests can both read ``indexing_status !=
"indexing"`` before either commits its own flip to ``"indexing"``, and
both would then successfully enqueue a task.

This module closes that race with a genuine distributed lock (Redis
``SET NX PX`` acquire, Lua compare-and-delete release) acquired by the
**task itself**, right before it does any real work — not just checked
at the API layer. Uses the same app-wide Redis client/DB as the
embedding/retrieval/reports caches (``app.db.redis.get_redis_client``):
the lock is small, TTL'd, applicaton-coordination state, not broker
protocol data, so it has no need of Celery's own, separate logical DB
(see ``CelerySettings``'s docstring for why *that* one is kept separate).
"""
from __future__ import annotations

import logging
import uuid

import redis.asyncio as redis

logger = logging.getLogger("codesage.ingestion.indexing_lock")

_LOCK_KEY_PREFIX = "codesage:indexing-lock"

# Atomic compare-and-delete: only release a lock this caller actually
# still holds (its own token matches), so a caller can never accidentally
# release a lock a *different* task has since (re-)acquired after this
# caller's own lock already expired on its own TTL.
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def lock_key_for(repository_id: uuid.UUID) -> str:
    """Build the Redis key for a repository's indexing lock.

    Exposed (not just an internal ``_lock_key`` helper) because
    cancellation (``WorkspaceService.cancel_indexing``) needs to clear a
    lock directly, without going through the normal acquire/release
    token flow (a cancelled task has no token to present).
    """
    return f"{_LOCK_KEY_PREFIX}:{repository_id}"


async def acquire_indexing_lock(client: redis.Redis, repository_id: uuid.UUID, ttl_seconds: int) -> str | None:
    """Attempt to atomically acquire the per-repository indexing lock.

    Args:
        client: The shared Redis client.
        repository_id: The repository being indexed.
        ttl_seconds: Safety-net expiry — long enough that a legitimately
            running task is never undercut, short enough that a worker
            that crashed without releasing the lock doesn't block
            re-indexing forever.

    Returns:
        A unique token identifying this acquisition (pass it to
        :func:`release_indexing_lock`), or ``None`` if another task
        already holds the lock.
    """
    token = uuid.uuid4().hex
    acquired = await client.set(lock_key_for(repository_id), token, nx=True, ex=ttl_seconds)
    return token if acquired else None


async def release_indexing_lock(client: redis.Redis, repository_id: uuid.UUID, token: str) -> bool:
    """Release the lock, but only if ``token`` still owns it.

    Args:
        client: The shared Redis client.
        repository_id: The repository that was being indexed.
        token: The token returned by the matching :func:`acquire_indexing_lock` call.

    Returns:
        ``True`` if this call released the lock; ``False`` if it had
        already expired or been taken over by a different task (never an
        error — a no-op release is always safe).
    """
    try:
        result = await client.eval(_RELEASE_SCRIPT, 1, lock_key_for(repository_id), token)
        return bool(result)
    except Exception:
        logger.warning("Failed to release indexing lock for repository %s (non-fatal)", repository_id, exc_info=True)
        return False
