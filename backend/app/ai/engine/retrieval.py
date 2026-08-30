"""Retrieval integration — a thin adapter to Sprint 4's RetrievalService (spec §3).

No semantic/lexical/structural/fusion/caching/reranking logic lives
here — this module only maps a classified intent to retrieval
parameters and delegates. ``RetrievalService`` is used completely
unmodified.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.ai.schemas.intent import QueryIntent
from app.retrieval.schemas import RetrievalQueryData
from app.retrieval.service import RetrievalService

# Per-intent retrieval-source tuning — only where a concrete reason
# exists (spec §3: "use query intent to select/adjust retrieval
# strategy only where justified"). Anything not listed uses
# RetrievalService's own defaults (all three sources) unchanged.
_INTENT_SOURCES: dict[QueryIntent, tuple[str, ...]] = {
    QueryIntent.DEPENDENCY_ANALYSIS: ("structural", "lexical"),
    QueryIntent.CALL_RELATIONSHIPS: ("structural", "lexical"),
    QueryIntent.SYMBOL_LOOKUP: ("lexical", "semantic"),
    QueryIntent.CONFIGURATION: ("lexical", "semantic"),
    QueryIntent.ARCHITECTURE_OVERVIEW: ("semantic", "structural"),
}

# A slightly larger candidate pool for questions that benefit from
# synthesizing across more evidence before Evidence Selection trims it
# back down (spec §4) — never unbounded (RetrievalSettings still caps
# every source independently).
_INTENT_TOP_K: dict[QueryIntent, int] = {
    QueryIntent.ARCHITECTURE_OVERVIEW: 15,
    QueryIntent.IMPACT_ANALYSIS: 15,
}


async def retrieve_evidence(
    *, session: AsyncSession, settings: Settings, repository_id: uuid.UUID, query: str, intent: QueryIntent,
    top_k_override: Optional[int] = None, sources_override: Optional[list[str]] = None,
    broaden: bool = False,
) -> RetrievalQueryData:
    """Run hybrid retrieval, tuned by the classified intent.

    Args:
        session: The active database session.
        settings: Application settings.
        repository_id: The repository to search — every result is
            guaranteed scoped to this id by ``RetrievalService`` itself.
        query: The user's raw query text.
        intent: The classified intent.
        top_k_override: An explicit caller override (from ``AskOptions``),
            takes precedence over intent-based tuning.
        sources_override: An explicit caller override, takes precedence
            over intent-based tuning.
        broaden: If ``True`` (the bounded verification-retry path),
            force all three sources and a larger top-K regardless of
            intent — a deliberately blunter, wider pass.

    Returns:
        Retrieval's ranked, evidence-bearing, already-deduplicated result set.
    """
    if broaden:
        sources: Optional[list[str]] = ["semantic", "lexical", "structural"]
        top_k = max(top_k_override or 0, _INTENT_TOP_K.get(intent, 10), 20)
    else:
        sources = sources_override if sources_override is not None else list(_INTENT_SOURCES.get(intent, ()) or [])
        sources = sources or None
        top_k = top_k_override or _INTENT_TOP_K.get(intent)

    service = RetrievalService(session, settings)
    return await service.query(repository_id, query, top_k, sources)
