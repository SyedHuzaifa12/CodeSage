"""Redis-backed retrieval-result cache.

A pure performance cache (CLAUDE.md §9: Redis is never a durable
store) — a miss, corruption, or Redis outage always just falls back to
recomputing the full retrieval pipeline, never an error surfaced to
the caller.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge import repository as knowledge_db
from app.retrieval.schemas import RetrievalQueryData

logger = logging.getLogger("codesage.retrieval.cache")


async def get_corpus_version(session: AsyncSession, repository_id: uuid.UUID) -> str:
    """Derive a version string that changes whenever a repository is re-indexed.

    Baked into the cache key (see ``retrieval/utils.py::cache_key``)
    rather than actively invalidated: a re-index naturally produces a
    different version, so any previously cached result for the old
    version is simply never looked up again and expires via TTL —
    exactly the pattern Sprint 3 uses for the embedding cache.

    Args:
        session: The active database session.
        repository_id: The repository being queried.

    Returns:
        ``"{total_chunks}:{embedding_model_version}:{last_indexed_at}"``,
        or ``"unindexed"`` if the repository has never been knowledge-indexed.
    """
    state = await knowledge_db.get_index_state(session, repository_id)
    if state is None:
        return "unindexed"
    last_indexed = state.last_indexed_at.isoformat() if state.last_indexed_at else "never"
    return f"{state.total_chunks}:{state.embedding_model_version}:{last_indexed}"


async def get_cached_result(client: redis.Redis, key: str) -> Optional[RetrievalQueryData]:
    """Fetch a previously cached retrieval response, if present and valid.

    Args:
        client: The shared Redis client.
        key: The cache key (see ``retrieval/utils.py::cache_key``).

    Returns:
        The cached response, or ``None`` on a miss, corrupt entry, or
        Redis being unreachable — every case is treated identically by
        the caller (recompute).
    """
    try:
        raw = await client.get(key)
    except Exception:
        logger.warning("Retrieval cache read failed; falling back to full computation", exc_info=True)
        return None
    if raw is None:
        return None
    try:
        return RetrievalQueryData.model_validate_json(raw)
    except Exception:
        logger.warning("Retrieval cache entry failed to deserialize; treating as a miss", exc_info=True)
        return None


async def set_cached_result(client: redis.Redis, key: str, data: RetrievalQueryData, ttl_seconds: int) -> None:
    """Best-effort write of a computed retrieval response into the cache.

    Args:
        client: The shared Redis client.
        key: The cache key.
        data: The response to cache.
        ttl_seconds: Cache entry lifetime.
    """
    try:
        await client.set(key, data.model_dump_json(), ex=ttl_seconds)
    except Exception:
        logger.warning("Retrieval cache write failed (non-fatal)", exc_info=True)
