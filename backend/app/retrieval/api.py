"""Retrieval REST API — routes only, no business logic (CLAUDE.md §10).

Kept intentionally small (one query endpoint): Sprint 4's scope is the
retrieval pipeline itself, exposed through a stable contract Sprint 5
(AI reasoning) and future MCP tool integration can build on directly.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.postgres import get_db
from app.retrieval.schemas import RetrievalQueryData
from app.retrieval.service import RetrievalService
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/repositories/{repository_id}/retrieval", tags=["retrieval"])


def get_retrieval_service(
    session: AsyncSession = Depends(get_db), settings: Settings = Depends(get_settings)
) -> RetrievalService:
    """Build a request-scoped :class:`RetrievalService`.

    Args:
        session: Injected database session.
        settings: Injected application settings (retrieval weights/limits).

    Returns:
        A service instance bound to this request's session.
    """
    return RetrievalService(session=session, settings=settings)


@router.get("/query", response_model=SuccessResponse[RetrievalQueryData])
async def query_retrieval(
    repository_id: uuid.UUID,
    q: str = Query(..., min_length=1, description="Free-text query."),
    top_k: Optional[int] = Query(default=None, ge=1, description="Maximum ranked results to return."),
    sources: Optional[str] = Query(
        default=None, description="Comma-separated subset of: semantic, lexical, structural."
    ),
    rerank: Optional[bool] = Query(
        default=None, description="Override the configured cross-encoder reranking on/off, for A/B comparison."
    ),
    service: RetrievalService = Depends(get_retrieval_service),
) -> SuccessResponse[RetrievalQueryData]:
    """Run the hybrid retrieval pipeline for one repository.

    Combines semantic (Qdrant), lexical (PostgreSQL trigram), and
    structural (Sprint 2A/2B relationship graph) retrieval into one
    deduplicated, ranked, evidence-bearing result set — never a plain
    vector-search-only response.

    Args:
        repository_id: The repository to search — every result is
            guaranteed to belong to this repository.
        q: The free-text query.
        top_k: Maximum ranked results (server-clamped to a configured maximum).
        sources: Optional comma-separated subset of retrieval sources,
            for isolating one strategy during testing/debugging
            (e.g. ``sources=semantic`` for semantic-only).
        rerank: Optional override for cross-encoder reranking, ignoring
            the configured default — lets the same running server
            answer both sides of a before/after quality comparison.
        service: Injected retrieval service.

    Returns:
        Ranked results with per-result evidence/scoring metadata, plus
        pipeline observability stats (candidate counts, per-stage
        latency, cache hit/miss).
    """
    source_list = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    data = await service.query(repository_id, q, top_k, source_list, rerank_override=rerank)
    message = "Retrieval results found." if data.results else "No matching results found."
    return SuccessResponse(message=message, data=data)
