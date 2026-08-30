"""Redis-backed AI-answer cache — structurally separate from Retrieval's own cache (spec §12).

Same pattern as ``app.retrieval.cache`` (a pure performance cache — a
miss, corruption, or Redis outage always falls back to recomputing the
full pipeline), but a distinct key prefix, TTL, and set of dimensions:
an AI answer additionally depends on the LLM provider/model and the
active prompt template version, neither of which affects a bare
retrieval query.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Optional

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompts.templates import PROMPT_VERSION
from app.ai.schemas.dto import AskResponseData
from app.core.config import LLMSettings
from app.retrieval.cache import get_corpus_version

logger = logging.getLogger("codesage.ai.cache")

_CACHE_KEY_PREFIX = "codesage:ai"


def build_cache_key(
    *, repository_id: uuid.UUID, normalized_query: str, top_k: Optional[int], sources: Optional[list[str]],
    corpus_version: str, llm_settings: LLMSettings,
) -> str:
    """Build the Redis key for one AI answer, covering every input that affects correctness.

    Args:
        repository_id: The repository being queried (never omit — the
            one guarantee that must never break: repository A's answer
            can never be served for repository B).
        normalized_query: The whitespace-normalized query text.
        top_k: The effective top-K override, if any.
        sources: The effective sources override, if any.
        corpus_version: The repository's current indexed-data version
            (see ``app.retrieval.cache.get_corpus_version`` — reused
            verbatim so a re-index invalidates the AI cache exactly the
            same way it already invalidates the retrieval cache).
        llm_settings: The active LLM settings — provider and model are
            part of the key so switching either never serves a stale answer.

    Returns:
        A stable cache key.
    """
    digest_input = "|".join(
        [
            str(repository_id), normalized_query.lower(), str(top_k), ",".join(sorted(sources or [])),
            corpus_version, llm_settings.llm_provider, _model_for(llm_settings), PROMPT_VERSION,
        ]
    )
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return f"{_CACHE_KEY_PREFIX}:{repository_id}:{digest}"


def _model_for(llm_settings: LLMSettings) -> str:
    return llm_settings.groq_model if llm_settings.llm_provider == "groq" else llm_settings.ollama_model


async def get_ai_corpus_version(session: AsyncSession, repository_id: uuid.UUID) -> str:
    """Return the corpus version this repository's AI answers should be keyed on.

    Args:
        session: The active database session.
        repository_id: The repository being queried.

    Returns:
        The same version string Retrieval's own cache uses — reused,
        not reimplemented, per spec §12 ("do not duplicate the
        Retrieval cache incorrectly").
    """
    return await get_corpus_version(session, repository_id)


async def get_cached_answer(client: redis.Redis, key: str) -> Optional[AskResponseData]:
    """Fetch a previously cached AI answer, if present and valid.

    Args:
        client: The shared Redis client.
        key: The cache key (see ``build_cache_key``).

    Returns:
        The cached response, or ``None`` on a miss, corrupt entry, or
        Redis being unreachable.
    """
    try:
        raw = await client.get(key)
    except Exception:
        logger.warning("AI answer cache read failed; falling back to full computation", exc_info=True)
        return None
    if raw is None:
        return None
    try:
        return AskResponseData.model_validate_json(raw)
    except Exception:
        logger.warning("AI answer cache entry failed to deserialize; treating as a miss", exc_info=True)
        return None


async def set_cached_answer(client: redis.Redis, key: str, response: AskResponseData, ttl_seconds: int) -> None:
    """Best-effort write of a computed AI answer into the cache.

    Args:
        client: The shared Redis client.
        key: The cache key.
        response: The response to cache.
        ttl_seconds: Cache entry lifetime.
    """
    try:
        await client.set(key, response.model_dump_json(), ex=ttl_seconds)
    except Exception:
        logger.warning("AI answer cache write failed (non-fatal)", exc_info=True)
