"""Application startup and shutdown lifecycle.

Startup fails fast: if PostgreSQL, Redis, or Qdrant cannot be reached,
the application raises immediately rather than starting in a silently
broken state. Shutdown closes every connection cleanly.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db.postgres import check_postgres_connection, close_postgres_connection
from app.db.qdrant import check_qdrant_connection, close_qdrant_connection
from app.db.redis import check_redis_connection, close_redis_connection
from app.exceptions.base import CacheConnectionError, DatabaseConnectionError, VectorStoreConnectionError

logger = logging.getLogger("codesage.lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Verify every dependency is reachable at startup; close all at shutdown.

    Args:
        app: The FastAPI application instance (unused directly, required
            by the lifespan protocol).

    Yields:
        Control back to FastAPI once startup checks succeed.

    Raises:
        DatabaseConnectionError: If PostgreSQL is unreachable at startup.
        CacheConnectionError: If Redis is unreachable at startup.
        VectorStoreConnectionError: If Qdrant is unreachable at startup.
    """
    logger.info("Starting CodeSage backend")

    if not await check_postgres_connection():
        raise DatabaseConnectionError("Unable to establish a PostgreSQL connection at startup.")
    logger.info("PostgreSQL connection verified")

    if not await check_redis_connection():
        raise CacheConnectionError("Unable to establish a Redis connection at startup.")
    logger.info("Redis connection verified")

    if not await check_qdrant_connection():
        raise VectorStoreConnectionError("Unable to establish a Qdrant connection at startup.")
    logger.info("Qdrant connection verified")

    yield

    logger.info("Shutting down CodeSage backend")
    await close_postgres_connection()
    await close_redis_connection()
    await close_qdrant_connection()
    logger.info("All connections closed cleanly")
