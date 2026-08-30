"""Semantic (vector) retrieval — Qdrant ``repository_chunks`` search.

Reuses Sprint 3's embedding provider and Qdrant collection verbatim;
this module only adds the query-time half (embed the query text, search
scoped to one repository, shape hits into candidates).
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from qdrant_client import AsyncQdrantClient

from app.knowledge.embedding import EmbeddingProvider
from app.knowledge.qdrant_store import search_points
from app.retrieval.candidates import Candidate, dedup_key_for

logger = logging.getLogger("codesage.retrieval.semantic")


async def get_semantic_candidates(
    *, qdrant_client: AsyncQdrantClient, provider: EmbeddingProvider, repository_id: uuid.UUID,
    query: str, limit: int, min_score: float = 0.0,
) -> list[Candidate]:
    """Embed the query and retrieve the most similar chunks for one repository.

    Args:
        qdrant_client: The shared async Qdrant client.
        provider: The active embedding provider (Sprint 3).
        repository_id: The repository to search within.
        query: The raw (or lightly normalized) query text.
        limit: Maximum candidates to return.
        min_score: Cosine-similarity floor. Vector search always
            returns its K nearest neighbors even when none are actually
            relevant, so without a floor "no relevant result" could
            never be a real outcome for semantic search — every query
            would return *something*. Note this is an imperfect signal
            for a small model on short code chunks (relevant and
            irrelevant scores can be close); it complements, not
            replaces, the lexical/structural sources' natural
            empty-result behavior.

    Returns:
        Candidates with a ``"semantic"`` source score (Qdrant's cosine
        similarity) — empty if the query is blank, the collection has
        no points for this repository yet, or every hit scored below
        ``min_score``.
    """
    if not query.strip():
        return []

    # Offloaded to a worker thread: model inference is synchronous,
    # CPU-bound work — running it inline would block the event loop for
    # its full duration, stalling every other concurrent request on
    # this process (a real, measured concern once reranking's own
    # inference is on the same path — see reranking.py).
    vector = (await asyncio.to_thread(provider.embed, [query]))[0]
    hits = await search_points(qdrant_client, repository_id, vector, limit)

    candidates: list[Candidate] = []
    for hit in hits:
        if hit.score < min_score:
            continue
        payload = hit.payload or {}
        file_id_raw = payload.get("file_id")
        if file_id_raw is None:
            continue  # defensive: a point without its own file_id is unusable as evidence
        symbol_id_raw = payload.get("symbol_id")
        chunk_id = uuid.UUID(str(hit.id))
        candidates.append(
            Candidate(
                dedup_key=dedup_key_for(
                    chunk_id=chunk_id, file_id=uuid.UUID(file_id_raw),
                    symbol_id=uuid.UUID(symbol_id_raw) if symbol_id_raw else None,
                ),
                repository_id=repository_id,
                file_id=uuid.UUID(file_id_raw),
                file_path=payload.get("file_path", ""),
                chunk_id=chunk_id,
                symbol_id=uuid.UUID(symbol_id_raw) if symbol_id_raw else None,
                start_line=payload.get("start_line"),
                end_line=payload.get("end_line"),
                language=payload.get("language"),
                source_scores={"semantic": float(hit.score)},
                reasons=[f"semantic similarity {hit.score:.2f}"],
            )
        )
    return candidates
