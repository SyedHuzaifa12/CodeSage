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
    settings = get_settings()
    return AsyncQdrantClient(
        host=settings.qdrant.qdrant_host,
        port=settings.qdrant.qdrant_http_port,
        grpc_port=settings.qdrant.qdrant_grpc_port,
        timeout=5,
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
