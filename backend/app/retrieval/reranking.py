"""Cross-encoder reranking — pre-Sprint-5 hardening pass.

Fusion (Sprint 4) only ever sees proxy signals: cosine similarity,
trigram similarity, relationship-type weight. None of them actually
read "does this text answer the query" — a cross-encoder does, scoring
the literal (query, candidate text) pair. Applied only to the fusion
stage's top candidate pool (bounded, configurable) — cross-encoders
cost one forward pass per candidate, so reranking the full candidate
set would defeat the sprint's latency requirements for no added value
(candidates ranked far outside the pool are already known-irrelevant).

Kept behind the same provider-interface pattern as
``knowledge/embedding.py`` so a future model swap or hosted reranking
API touches only this file.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.config import RetrievalSettings, get_settings
from app.models.repository import Repository
from app.retrieval.candidates import Candidate

logger = logging.getLogger("codesage.retrieval.reranking")


class RerankProvider(Protocol):
    """Interface every reranking backend must implement."""

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Score each document's relevance to the query.

        Args:
            query: The user's query text.
            documents: Candidate document texts, in order.

        Returns:
            One relevance score per document, same order — higher is
            more relevant. Not bounded to any fixed range (raw
            cross-encoder logits); only relative order/magnitude
            within one call is meaningful.
        """
        ...


class CrossEncoderRerankProvider:
    """Local, offline reranker backed by ``fastembed``'s ONNX cross-encoder.

    Same library already in the stack for embeddings (Sprint 3) — no
    new dependency. ``ms-marco-MiniLM-L-6-v2`` is a small (~80MB),
    widely-used, CPU-fast reranking model.
    """

    def __init__(self, settings: RetrievalSettings) -> None:
        """Load the configured cross-encoder model.

        Args:
            settings: The active retrieval settings.
        """
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        from app.core.config import get_settings as _get_settings

        cache_dir = _get_settings().llm.embedding_model_cache_dir
        load_started = time.perf_counter()
        self._model = TextCrossEncoder(model_name=settings.reranking_model, cache_dir=cache_dir)
        logger.info(
            "Loaded reranking model '%s' in %dms", settings.reranking_model,
            int((time.perf_counter() - load_started) * 1000),
        )

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """Score each document's relevance to the query.

        Args:
            query: The user's query text.
            documents: Candidate document texts, in order.

        Returns:
            One relevance score per document, same order.
        """
        if not documents:
            return []
        return [float(score) for score in self._model.rerank(query, documents)]


@lru_cache
def get_rerank_provider() -> RerankProvider:
    """Return the process-wide cached reranking provider.

    Mirrors ``knowledge/embedding.py::get_embedding_provider``'s
    no-argument, settings-read-inside pattern (``RetrievalSettings`` is
    a mutable Pydantic model and therefore not hashable).

    Returns:
        A ready-to-use reranking provider.
    """
    return CrossEncoderRerankProvider(get_settings().retrieval)


def read_candidate_text(repository: Repository, candidate: Candidate, max_chars: int = 4000) -> str | None:
    """Re-read a candidate's exact source lines from the repository's local clone.

    Chunk text is never persisted in Postgres or Qdrant (Sprint 3
    stores only line ranges + embeddings) — reranking needs the actual
    text, so it's read back from disk, bounded to this one candidate's
    known line range (never a full-file scan).

    Args:
        repository: The owning repository (for its local clone path).
        candidate: The candidate to read text for.
        max_chars: Safety cap in case of a pathological line range.

    Returns:
        The candidate's source text, or ``None`` if it can no longer be
        read (file deleted/renamed/binary since indexing) — the caller
        must treat this as "skip reranking for this one candidate", not
        a fatal error.
    """
    if candidate.start_line is None or candidate.end_line is None:
        return None
    try:
        absolute_path = Path(repository.local_path) / candidate.file_path
        lines = absolute_path.read_text(encoding="utf-8").splitlines()
        text = "\n".join(lines[candidate.start_line - 1 : candidate.end_line])
        return text[:max_chars] if text.strip() else None
    except (OSError, UnicodeDecodeError):
        return None
