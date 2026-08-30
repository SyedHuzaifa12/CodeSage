"""Structural retrieval — one-hop expansion over Sprint 2A/2B's relationship graph.

Given a handful of "seed" symbols already found by semantic/lexical
retrieval, this surfaces their directly connected symbols (callers,
callees, implementers, dependents, ...) as additional candidates.
Deliberately one hop only — expanding further (callers of callers, and
so on) is the "unrestricted graph traversal" this sprint excludes;
that belongs to a future, explicitly-scoped Retrieval/Knowledge
capability, not a default of every query.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.relationship import Relationship
from app.retrieval.candidates import Candidate, dedup_key_for
from app.retrieval.repository import get_relationships_touching, get_symbols_by_qualified_names

logger = logging.getLogger("codesage.retrieval.structural")

# Relative importance of each relationship type as a structural
# relevance signal — a direct call/inheritance edge is a stronger
# "you probably want to see this too" signal than a broad import or
# containment edge. Deliberately a small, hand-picked, documented table
# rather than a learned weight (§6: "do not invent arbitrary ML scores").
_RELATIONSHIP_TYPE_SCORE: dict[str, float] = {
    "calls": 0.70,
    "extends": 0.65,
    "implements": 0.65,
    "depends_on": 0.55,
    "imports": 0.45,
    "belongs_to": 0.35,
}
_DEFAULT_RELATIONSHIP_SCORE = 0.4


async def get_structural_candidates(
    *, session: AsyncSession, repository_id: uuid.UUID, seed_candidates: list[Candidate],
    max_seeds: int, max_related: int,
) -> list[Candidate]:
    """Expand a set of seed candidates one hop along the relationship graph.

    Args:
        session: The active database session.
        repository_id: The repository to search within.
        seed_candidates: Candidates from semantic/lexical retrieval that
            carry a resolved ``qualified_name`` (candidates without one
            — e.g. a fallback-chunk hit with no symbol — contribute no
            seed and are simply skipped here).
        max_seeds: Maximum distinct seed symbols to expand from.
        max_related: Maximum relationship rows fetched (bounds the
            entire expansion, independent of repository size).

    Returns:
        Candidates with a ``"structural"`` source score — empty if no
        seed had a resolvable qualified name, or none had any
        relationships.
    """
    seed_names = list(dict.fromkeys(c.qualified_name for c in seed_candidates if c.qualified_name))[:max_seeds]
    if not seed_names:
        return []

    relationships = await get_relationships_touching(session, repository_id, seed_names, max_related)
    if not relationships:
        return []

    related_names: set[str] = set()
    relationships_by_related_name: dict[str, list[Relationship]] = {}
    for relationship in relationships:
        if relationship.source_symbol in seed_names and relationship.target_symbol not in seed_names:
            other = relationship.target_symbol
        elif relationship.target_symbol in seed_names and relationship.source_symbol not in seed_names:
            other = relationship.source_symbol
        else:
            continue
        related_names.add(other)
        relationships_by_related_name.setdefault(other, []).append(relationship)

    resolved = await get_symbols_by_qualified_names(session, repository_id, list(related_names), max_related)

    candidates: list[Candidate] = []
    for symbol, file_path in resolved:
        related_relationships = relationships_by_related_name.get(symbol.qualified_name, [])
        relationship_types = sorted({r.relationship_type for r in related_relationships})
        score = max(_RELATIONSHIP_TYPE_SCORE.get(t, _DEFAULT_RELATIONSHIP_SCORE) for t in relationship_types)
        candidates.append(
            Candidate(
                dedup_key=dedup_key_for(chunk_id=None, file_id=symbol.file_id, symbol_id=symbol.id),
                repository_id=repository_id,
                file_id=symbol.file_id,
                file_path=file_path,
                symbol_id=symbol.id,
                symbol_name=symbol.name,
                qualified_name=symbol.qualified_name,
                symbol_type=symbol.symbol_type,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                source_scores={"structural": score},
                reasons=[f"{rtype} relationship to a matched result" for rtype in relationship_types],
            )
        )
    return candidates
