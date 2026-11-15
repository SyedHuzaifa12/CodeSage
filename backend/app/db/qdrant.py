"""Qdrant connection infrastructure.

Provides a lazily-created, process-wide async Qdrant client, a FastAPI
dependency, and connectivity/shutdown helpers. No collections are
created here — that is Knowledge module work, out of scope for this
infrastructure sprint.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from functools import lru_cache

from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings

logger = logging.getLogger("codesage.db.qdrant")


@lru_cache
def get_qdrant_client() -> AsyncQdrantClient:
    """Return the process-wide cached async Qdrant client.

    Returns:
        A configured :class:`~qdrant_client.AsyncQdrantClient`.
    """
    cfg = get_settings().qdrant
    api_key = cfg.qdrant_api_key.get_secret_value() if cfg.qdrant_api_key else None
    timeout = int(cfg.qdrant_timeout_seconds)
    if cfg.qdrant_url:
        # Qdrant Cloud: HTTPS + API key. gRPC is not used (the free tier's REST endpoint is enough).
        # check_compatibility=False: the client's version probe is a blocking HTTP call made while the
        # client is being constructed, which would stall the event loop if the cluster is waking up.
        return AsyncQdrantClient(
            url=cfg.qdrant_url, api_key=api_key, timeout=timeout, prefer_grpc=False, check_compatibility=False
        )
    return AsyncQdrantClient(
        host=cfg.qdrant_host,
        port=cfg.qdrant_http_port,
        grpc_port=cfg.qdrant_grpc_port,
        api_key=api_key,
        timeout=timeout,
        check_compatibility=False,
    )


async def get_qdrant() -> AsyncIterator[AsyncQdrantClient]:
    """FastAPI dependency yielding the shared Qdrant client.

    Yields:
        The process-wide Qdrant client.
    """
    yield get_qdrant_client()


async def check_qdrant_connection() -> bool:
    """Verify Qdrant connectivity by listing collections.

    Returns:
        ``True`` if Qdrant responds, ``False`` otherwise.
    """
    try:
        client = get_qdrant_client()
        await client.get_collections()
        return True
    except Exception:
        logger.exception("Qdrant health check failed")
        return False


async def close_qdrant_connection() -> None:
    """Close the shared Qdrant client's connections on application shutdown."""
    client = get_qdrant_client()
    await client.close()
    get_qdrant_client.cache_clear()
