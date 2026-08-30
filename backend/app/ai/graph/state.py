"""The AI pipeline's state contract — what flows through every LangGraph node.

Kept as a plain ``TypedDict`` (not a Pydantic model): LangGraph reads
and merges state via dict operations, and this graph runs entirely
in-process for a single request with no checkpointer/persistence, so
there is nothing to (de)serialize — the extra validation overhead of a
Pydantic model on every node transition would be pure cost.
"""
from __future__ import annotations

import uuid
from typing import Optional, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.schemas.intent import IntentAnalysis
from app.ai.schemas.verification import VerificationResult
from app.core.config import Settings
from app.models.repository import Repository
from app.retrieval.schemas import EvidenceResult, RetrievalQueryData


class EvidenceWithText(TypedDict, total=False):
    """One selected evidence item, enriched with its actual source text.

    ``app.retrieval.schemas.EvidenceResult`` never carries source text
    (Sprint 3 doesn't persist chunk text anywhere) — this is that same
    evidence item plus the text read back from disk for this request
    (see ``ai/engine/context.py``, reusing
    ``app.retrieval.reranking.read_candidate_text``).
    """

    file_path: str
    symbol_name: Optional[str]
    symbol_type: Optional[str]
    start_line: Optional[int]
    end_line: Optional[int]
    retrieval_score: float
    retrieval_sources: list[str]
    text: Optional[str]


class LLMAnswer(TypedDict, total=False):
    """The raw output of the reasoning stage, before verification/formatting."""

    text: str
    provider: str
    model: str
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]


class AIGraphState(TypedDict, total=False):
    """The full state object threaded through every node of the AI pipeline graph."""

    # --- inputs, set once before the graph runs ---
    request_id: str
    repository_id: uuid.UUID
    repository: Repository
    query: str
    top_k_override: Optional[int]
    sources_override: Optional[list[str]]
    session: AsyncSession
    settings: Settings

    # --- populated stage by stage ---
    intent: IntentAnalysis
    retrieval_result: RetrievalQueryData
    selected_results: list[EvidenceResult]  # post select_evidence(), pre text-enrichment
    selected_evidence: list[EvidenceWithText]  # post build_context(): the same items, enriched with source text
    context_text: str
    llm_answer: LLMAnswer
    verification: VerificationResult
    final_response: object  # app.ai.schemas.dto.AskResponseData — typed loosely to avoid an import cycle with formatter.py

    # --- control flow ---
    retry_count: int
    force_insufficient: bool  # set when evidence was too sparse to even call the LLM

    # --- observability ---
    stage_latency_ms: dict[str, int]
