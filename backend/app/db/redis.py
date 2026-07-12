"""Redis connection infrastructure.

Provides a lazily-created, process-wide Redis client (which manages its
own internal connection pool and is therefore safe to reuse across
requests), a FastAPI dependency, and connectivity/shutdown helpers.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from functools import lru_cache

import redis.asyncio as redis

from app.core.config import get_settings

logger = logging.getLogger("codesage.db.redis")


@lru_cache
def get_redis_client() -> redis.Redis:
    """Return the process-wide cached Redis client.

    A single ``redis.asyncio.Redis`` instance already pools and reuses
    its underlying connections, so caching one instance per process is
    sufficient — no separate pool object is required.

    Returns:
        A configured async Redis client.
    """
    settings = get_settings()
    password = settings.redis.redis_password.get_secret_value() if settings.redis.redis_password else None
    return redis.Redis(
        host=settings.redis.redis_host,
        port=settings.redis.redis_port,
        db=settings.redis.redis_db,
        password=password,
        decode_responses=True,
        socket_connect_timeout=5,
    )


async def get_redis() -> AsyncIterator[redis.Redis]:
    """FastAPI dependency yielding the shared Redis client.

    Yields:
        The process-wide Redis client.
    """
    yield get_redis_client()


async def check_redis_connection() -> bool:
    """Verify Redis connectivity via ``PING``.

    Returns:
        ``True`` if Redis responds, ``False`` otherwise.
    """
    try:
        client = get_redis_client()
        return bool(await client.ping())
    except Exception:
        logger.exception("Redis health check failed")
        return False


async def close_redis_connection() -> None:
    """Close the shared Redis client's connections on application shutdown."""
    client = get_redis_client()
    await client.aclose()
    get_redis_client.cache_clear()
