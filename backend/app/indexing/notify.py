"""Wake the indexer and keep it awake while a job runs (ADR-028).

The indexer sleeps when idle (free hosts spin down after ~15 minutes without
inbound traffic) and never polls for work, so the API has to tell it when
there is some. Both calls are best effort: a lost wake is harmless because
the job stays ``queued`` in Postgres and is picked up on the next wake, and
the status polls that happen while a job is active keep sending wakes.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.config import Settings, get_settings
from app.db.redis import get_redis_client
from app.indexing.registry import get_runner

logger = logging.getLogger("codesage.indexing.notify")

_PING_KEY = "codesage:indexer-ping"


def is_postgres_backend(settings: Optional[Settings] = None) -> bool:
    """Whether indexing is dispatched through the Postgres queue (as opposed to Celery)."""
    return (settings or get_settings()).indexing.indexing_backend == "postgres"


async def wake_indexer(settings: Optional[Settings] = None, *, path: str = "wake") -> None:
    """Tell the indexer there may be work. Never raises.

    In a process that hosts the runner itself (``ROLE=all``) this is a function call;
    otherwise it is an authenticated HTTP request to ``INDEXER_URL``. The request is
    expected to be slow when the indexer is asleep (the host boots to answer it), so it is
    meant to be run as a background task, not awaited inside a request.
    """
    settings = settings or get_settings()
    runner = get_runner()
    if runner is not None:
        runner.wake()
        return

    url = settings.indexing.indexer_url
    token = settings.auth.internal_api_token
    if not url or token is None:
        logger.warning("Cannot wake the indexer: INDEXER_URL and INTERNAL_API_TOKEN must both be set.")
        return
    endpoint = f"{url}{settings.app.api_v1_prefix}/internal/{path}"
    try:
        async with httpx.AsyncClient(timeout=settings.indexing.indexer_wake_timeout_seconds) as client:
            response = await client.post(endpoint, headers={"X-Internal-Token": token.get_secret_value()})
        if response.status_code >= 400:
            logger.warning("Indexer %s call returned HTTP %d", path, response.status_code)
    except httpx.HTTPError as exc:
        logger.warning("Indexer %s call failed (%s); the job stays queued until the next wake.", path, type(exc).__name__)


async def ping_indexer_if_due(settings: Optional[Settings] = None) -> None:
    """Rate-limited keep-alive, called while a user is watching an active job.

    The frontend polls repository status every couple of seconds; forwarding every poll would
    hammer the indexer, so at most one ping per ``indexer_ping_min_interval_seconds`` goes out
    (cluster-wide, via Redis). Skipped silently if Redis is unavailable.
    """
    settings = settings or get_settings()
    try:
        acquired = await get_redis_client().set(
            _PING_KEY, "1", nx=True, ex=settings.indexing.indexer_ping_min_interval_seconds
        )
    except Exception:  # noqa: BLE001 -- a missing rate limiter must not become a request failure
        return
    if acquired:
        await wake_indexer(settings, path="heartbeat")
