"""AI Engine API request/response DTOs — validation only, no business logic."""
from __future__ import annotations

import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class AskOptions(BaseModel):
    """Optional per-request overrides — all default to configuration-driven behavior."""

    top_k: Optional[int] = Field(default=None, ge=1, description="Override the retrieval top-K.")
    sources: Optional[list[str]] = Field(
        default=None, description="Override retrieval sources (subset of semantic/lexical/structural)."
    )
    force_refresh: bool = Field(default=False, description="Bypass the AI answer cache for this request.")


class AskRequest(BaseModel):
    """Request body for ``POST /repositories/{id}/ask``."""

    query: str = Field(..., min_length=1)
    options: Optional[AskOptions] = None


class Citation(BaseModel):
    """A single piece of repository evidence the answer relied on — first-class, per spec §10.

    Every field here corresponds to an actual, verified retrieval
    result (``app.retrieval.schemas.EvidenceResult``) — never
    fabricated by the LLM.
    """

    model_config = ConfigDict(from_attributes=True)

    file_path: str
    symbol_name: Optional[str] = None
    symbol_type: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    retrieval_score: float
    retrieval_sources: list[str]


class VerificationInfo(BaseModel):
    """The verification gate's outcome, exposed to the caller."""

    status: str
    reasons: list[str]


class StageLatency(BaseModel):
    """Per-stage timing breakdown, for observability (spec §11/§16)."""

    intent_ms: int = 0
    retrieval_ms: int = 0
    evidence_selection_ms: int = 0
    context_construction_ms: int = 0
    llm_ms: int = 0
    verification_ms: int = 0
    formatting_ms: int = 0
    total_ms: int = 0


class AskMetadata(BaseModel):
    """Everything about *how* the answer was produced, separate from the answer itself."""

    intent: str
    provider: str
    model: str
    cache_hit: bool
    retry_count: int
    stage_latency_ms: StageLatency
    retrieval_candidates: int
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


class AskResponseData(BaseModel):
    """Payload shape for ``POST /repositories/{id}/ask``."""

    repository_id: uuid.UUID
    query: str
    answer: str
    explanation: Optional[str] = None
    evidence: list[Citation]
    relevant_files: list[str]
    relevant_symbols: list[str]
    verification: VerificationInfo
    metadata: AskMetadata
