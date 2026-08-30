"""Redis-backed report cache — mirrors ``app.ai.cache``'s pattern exactly.

A pure performance cache (CLAUDE.md §9): a miss, corrupt entry, or
Redis outage always falls back to the full generation pipeline, never
an error. Own key prefix (``codesage:reports``), distinct from both
Retrieval's and the AI Engine's cache namespaces (spec §13: "never
allow cache entries to cross repository boundaries" — enforced here by
always including ``repository_id`` in both the key's digest input and
its visible prefix, matching ``ai/cache.py``'s same defense-in-depth
approach).
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from typing import Optional

import redis.asyncio as redis

from app.core.config import LLMSettings
from app.reports.schemas import ReportResponse

logger = logging.getLogger("codesage.reports.cache")

_CACHE_KEY_PREFIX = "codesage:reports"

# Bump whenever a generator's deterministic-collection or evidence-
# assembly logic changes materially — baked into the cache key so a
# generator bugfix/behavior change can never silently keep serving a
# report computed under the old logic (mirrors ``ai/prompts/templates.py``'s
# ``PROMPT_VERSION`` role in ``ai/cache.py``).
REPORT_GENERATOR_VERSION = "v1"


def build_cache_key(
    *, repository_id: uuid.UUID, report_type: str, repository_version: str, llm_settings: Optional[LLMSettings] = None,
) -> str:
    """Build the Redis key for one repository's report of one type.

    Args:
        repository_id: The repository the report belongs to — never
            omit: this is the one guarantee that must never break
            (spec §13/§19 — repository A's report can never be served
            for repository B).
        report_type: The internal report type (``summary``,
            ``architecture``, ``dependency_risk``, ``health``, ``onboarding``).
        repository_version: The repository's current indexed-data
            version (see ``app.retrieval.cache.get_corpus_version``,
            reused verbatim so a re-index invalidates report caches the
            same way it already invalidates retrieval/AI caches).
        llm_settings: The active LLM settings, if this report type may
            use AI synthesis — provider/model are part of the key so
            switching either never serves a report synthesized under a
            different model.

    Returns:
        A stable cache key, namespaced by repository id for readability
        and defense-in-depth alongside the digest.
    """
    provider = llm_settings.llm_provider if llm_settings else "none"
    model = (llm_settings.groq_model if llm_settings.llm_provider == "groq" else llm_settings.ollama_model) if llm_settings else "none"
    digest_input = "|".join(
        [str(repository_id), report_type, repository_version, REPORT_GENERATOR_VERSION, provider, model]
    )
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return f"{_CACHE_KEY_PREFIX}:{repository_id}:{report_type}:{digest}"


async def get_cached_report(client: redis.Redis, key: str) -> Optional[ReportResponse]:
    """Fetch a previously cached report, if present and valid.

    Args:
        client: The shared Redis client.
        key: The cache key (see ``build_cache_key``).

    Returns:
        The cached report, or ``None`` on a miss, corrupt entry, or
        Redis being unreachable.
    """
    try:
        raw = await client.get(key)
    except Exception:
        logger.warning("Report cache read failed; falling back to full generation", exc_info=True)
        return None
    if raw is None:
        return None
    try:
        return ReportResponse.model_validate_json(raw)
    except Exception:
        logger.warning("Report cache entry failed to deserialize; treating as a miss", exc_info=True)
        return None


async def set_cached_report(client: redis.Redis, key: str, report: ReportResponse, ttl_seconds: int) -> None:
    """Best-effort write of a computed report into the cache.

    Args:
        client: The shared Redis client.
        key: The cache key.
        report: The report to cache.
        ttl_seconds: Cache entry lifetime.
    """
    try:
        await client.set(key, report.model_dump_json(), ex=ttl_seconds)
    except Exception:
        logger.warning("Report cache write failed (non-fatal)", exc_info=True)
