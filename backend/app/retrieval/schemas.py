"""Retrieval request/response DTOs — validation only, no business logic."""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict


class SourceScore(BaseModel):
    """One retrieval source's raw contribution to a result's final score."""

    source: str
    score: float


class EvidenceResult(BaseModel):
    """A single ranked, evidence-bearing retrieval result.

    Carries everything Sprint 5 needs to ground an answer and cite its
    source: enough identity to fetch the exact lines back from the
    repository's clone, plus the scoring/explanation trail for why this
    result was surfaced.
    """

    model_config = ConfigDict(from_attributes=True)

    rank: int
    final_score: float
    rerank_score: Optional[float] = None
    repository_id: uuid.UUID
    file_id: uuid.UUID
    file_path: str
    chunk_id: Optional[uuid.UUID]
    symbol_id: Optional[uuid.UUID]
    symbol_name: Optional[str]
    qualified_name: Optional[str]
    symbol_type: Optional[str]
    start_line: Optional[int]
    end_line: Optional[int]
    language: Optional[str]
    sources: list[str]
    source_scores: list[SourceScore]
    reasons: list[str]


class RetrievalStats(BaseModel):
    """Per-source candidate counts and per-stage latency, for observability."""

    candidates_semantic: int
    candidates_lexical: int
    candidates_structural: int
    candidates_after_dedup: int
    stage_latency_ms: dict[str, int]
    total_latency_ms: int
    cache_hit: bool
    sources_failed: list[str]
    reranking_applied: bool = False


class RetrievalQueryData(BaseModel):
    """Payload shape for ``GET /repositories/{id}/retrieval/query``."""

    repository_id: uuid.UUID
    query: str
    top_k: int
    sources_requested: list[str]
    results: list[EvidenceResult]
    stats: RetrievalStats
