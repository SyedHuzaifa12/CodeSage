"""PostgreSQL connection infrastructure.

Connection and schema-verification only — no CRUD, no business queries.
Tables are created exclusively through Alembic migrations (CLAUDE.md §9:
"never hand-edit tables"), so this module checks that the expected
schema exists rather than ever creating it itself. Provides a
lazily-created, process-wide engine, a FastAPI dependency for
request-scoped sessions, and connectivity/shutdown helpers used by the
application lifespan and health endpoints.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

logger = logging.getLogger("codesage.db.postgres")


@lru_cache
def get_engine() -> AsyncEngine:
    """Return the process-wide cached async SQLAlchemy engine.

    Cached so the connection pool is created once per process. Creating
    the engine does not open a connection — that happens lazily on first
    use, satisfying the lazy-initialization requirement.

    Returns:
        A configured :class:`~sqlalchemy.ext.asyncio.AsyncEngine`.
    """
    settings = get_settings()
    return create_async_engine(
        settings.database.async_dsn,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        future=True,
    )


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the cached engine.

    Returns:
        An :class:`~sqlalchemy.ext.asyncio.async_sessionmaker` producing
        :class:`~sqlalchemy.ext.asyncio.AsyncSession` instances.
    """
    return async_sessionmaker(bind=get_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped database session.

    Commits once the route handler completes without error, or rolls
    back if it raised — callers never need to manage the transaction
    themselves, avoiding scattered ``commit()``/``rollback()`` calls
    across every service.

    Yields:
        An :class:`~sqlalchemy.ext.asyncio.AsyncSession` closed automatically
        at the end of the request.
    """
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_postgres_connection() -> bool:
    """Verify PostgreSQL connectivity with a lightweight round-trip query.

    Returns:
        ``True`` if the database responds, ``False`` otherwise.
    """
    try:
        engine = get_engine()
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.exception("PostgreSQL health check failed")
        return False


def _get_table_names(sync_connection) -> set[str]:
    """Synchronous helper run via ``AsyncConnection.run_sync`` to inspect tables."""
    return set(inspect(sync_connection).get_table_names())


async def verify_schema_initialized() -> bool:
    """Check that every model-defined table exists in the connected database.

    Compares :data:`app.models.Base.metadata`'s registered tables against
    what actually exists in PostgreSQL. Never creates or alters
    anything — schema changes only ever happen through Alembic.

    Returns:
        ``True`` if every expected table exists, ``False`` otherwise
        (including on any connectivity error).
    """
    from app.models import Base

    expected_tables = set(Base.metadata.tables.keys())
    try:
        engine = get_engine()
        async with engine.connect() as connection:
            connection: AsyncConnection
            existing_tables = await connection.run_sync(_get_table_names)
    except Exception:
        logger.exception("Database schema verification failed")
        return False

    missing_tables = expected_tables - existing_tables
    if missing_tables:
        logger.error("Missing database tables: %s", sorted(missing_tables))
        return False
    return True


async def close_postgres_connection() -> None:
    """Dispose of the engine's connection pool on application shutdown."""
    engine = get_engine()
    await engine.dispose()
    get_engine.cache_clear()
