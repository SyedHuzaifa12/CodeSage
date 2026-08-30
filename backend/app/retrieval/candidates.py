"""Internal retrieval-candidate model, deduplication, and score fusion.

Kept separate from ``schemas.py`` deliberately: this is the computation
model every retrieval source produces and the fusion stage consumes,
not the API's wire format — a future reranking stage (explicitly out of
scope for Sprint 4) plugs in here without touching the API layer.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Candidate:
    """One retrieval hit, before or after fusion.

    Identity for deduplication/merging is ``dedup_key`` — never object
    identity — so the same underlying chunk/symbol found by two
    different retrieval sources merges into one candidate instead of
    appearing twice.
    """

    dedup_key: str
    repository_id: uuid.UUID
    file_id: uuid.UUID
    file_path: str
    chunk_id: Optional[uuid.UUID] = None
    symbol_id: Optional[uuid.UUID] = None
    symbol_name: Optional[str] = None
    qualified_name: Optional[str] = None
    symbol_type: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    language: Optional[str] = None

    # source name -> raw score (each source's own 0..1-ish scale)
    source_scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    final_score: float = 0.0
    rerank_score: Optional[float] = None

    def merge(self, other: "Candidate") -> None:
        """Fold another candidate found for the same ``dedup_key`` into this one.

        Args:
            other: A candidate identified as a duplicate of this one —
                its source scores and reasons are absorbed; whichever
                side has richer identity fields (symbol info, line
                ranges) is kept, never overwritten with a blanker one.
        """
        for source, score in other.source_scores.items():
            self.source_scores[source] = max(self.source_scores.get(source, 0.0), score)
        for reason in other.reasons:
            if reason not in self.reasons:
                self.reasons.append(reason)
        if self.symbol_id is None and other.symbol_id is not None:
            self.symbol_id = other.symbol_id
            self.symbol_name = other.symbol_name
            self.qualified_name = other.qualified_name
            self.symbol_type = other.symbol_type
        if self.chunk_id is None and other.chunk_id is not None:
            self.chunk_id = other.chunk_id
        if self.start_line is None and other.start_line is not None:
            self.start_line = other.start_line
            self.end_line = other.end_line


def dedup_key_for(
    *, chunk_id: Optional[uuid.UUID], file_id: uuid.UUID, symbol_id: Optional[uuid.UUID]
) -> str:
    """Compute the identity a candidate is deduplicated on.

    Preference order: a chunk id is the most specific identity
    (exact lines of exact text); a symbol id is the next most specific
    (same symbol, possibly reached without a known chunk, e.g. a
    structural hit); a bare file id is the fallback for a whole-file
    match with neither.

    Args:
        chunk_id: The candidate's chunk id, if known.
        file_id: The candidate's owning file id (always known).
        symbol_id: The candidate's symbol id, if known.

    Returns:
        A stable string key two candidates share only if they represent
        the same underlying evidence.
    """
    if chunk_id is not None:
        return f"chunk:{chunk_id}"
    if symbol_id is not None:
        return f"symbol:{symbol_id}"
    return f"file:{file_id}"


def deduplicate(candidates: list[Candidate]) -> list[Candidate]:
    """Merge candidates sharing the same ``dedup_key``, preserving first-seen order.

    Args:
        candidates: Raw candidates from one or more retrieval sources,
            in the order their source calls completed.

    Returns:
        One candidate per unique ``dedup_key``.
    """
    merged: dict[str, Candidate] = {}
    order: list[str] = []
    for candidate in candidates:
        existing = merged.get(candidate.dedup_key)
        if existing is None:
            merged[candidate.dedup_key] = candidate
            order.append(candidate.dedup_key)
        else:
            existing.merge(candidate)
    return [merged[key] for key in order]


_TEST_INTENT_WORDS = frozenset({"test", "tests", "testing", "spec", "specs"})
_TEST_PATH_MARKERS = ("test_", "_test.py", "test.py", "tests.py", "/test/", "/tests/", "/__tests__/", ".test.", ".spec.")


def query_has_test_intent(normalized_query: str) -> bool:
    """Detect a generic testing-intent word in the query — repository-agnostic by design.

    A deterministic, English-word-based signal (never tuned to any
    specific repository's content or naming) — "which tests cover X"
    should favor test files over implementation files regardless of
    what the repository or its tests are actually called.

    Args:
        normalized_query: The whitespace-normalized query text.

    Returns:
        ``True`` if any whitespace-separated word matches a testing-intent term.
    """
    words = {w.strip(".,?!:;").lower() for w in normalized_query.split()}
    return bool(words & _TEST_INTENT_WORDS)


def _looks_like_test_path(file_path: str) -> bool:
    """Check whether a file path matches a common test-file naming convention.

    Deliberately duplicated (not imported) from
    ``ingestion/intelligence_service.py``'s equivalent heuristic — a
    three-line, stable convention check isn't worth a cross-module
    dependency between Ingestion and Retrieval.

    Args:
        file_path: A repository-relative file path.

    Returns:
        ``True`` if the path matches a common test-file convention.
    """
    lowered = f"/{file_path.lower()}"
    return any(marker in lowered for marker in _TEST_PATH_MARKERS)


def fuse_and_rank(
    candidates: list[Candidate],
    *,
    weight_semantic: float,
    weight_lexical: float,
    weight_structural: float,
    entry_point_boost: float,
    hotspot_boost: float,
    entry_point_paths: frozenset[str],
    hotspot_module_paths: frozenset[str],
    top_k: int,
    test_intent_boost: float = 0.0,
    query_test_intent: bool = False,
) -> list[Candidate]:
    """Compute each candidate's final fused score and return the top-K, ranked.

    Deterministic and explainable by construction: the final score is a
    fixed linear combination of named, inspectable components (never a
    black-box model), and ties break on ``(file_path, start_line)`` so
    the same inputs always produce the same ordering.

    Args:
        candidates: Deduplicated candidates.
        weight_semantic: Weight applied to the ``"semantic"`` source score.
        weight_lexical: Weight applied to the ``"lexical"`` source score.
        weight_structural: Weight applied to the ``"structural"`` source score.
        entry_point_boost: Flat bonus for a candidate whose file is a
            known repository entry point (Sprint 2B's ``entry_points``).
        hotspot_boost: Flat bonus for a candidate whose file is a known
            dependency hotspot (Sprint 2B's ``dependency_hotspots``).
        entry_point_paths: Repository-relative paths of entry points.
        hotspot_module_paths: Module paths of dependency hotspots.
        top_k: Maximum results to return.
        test_intent_boost: Flat bonus for a candidate in a test file,
            applied only when ``query_test_intent`` is true.
        query_test_intent: Whether the query contains a generic
            testing-intent word (see ``query_has_test_intent``).

    Returns:
        The highest-scoring candidates, descending, length <= ``top_k``.
    """
    for candidate in candidates:
        score = (
            weight_semantic * candidate.source_scores.get("semantic", 0.0)
            + weight_lexical * candidate.source_scores.get("lexical", 0.0)
            + weight_structural * candidate.source_scores.get("structural", 0.0)
        )
        if candidate.file_path in entry_point_paths:
            score += entry_point_boost
            candidate.reasons.append("file is a repository entry point")
        module_path = candidate.file_path.rsplit(".", 1)[0].replace("/", ".")
        if module_path in hotspot_module_paths:
            score += hotspot_boost
            candidate.reasons.append("file is a dependency hotspot")
        if query_test_intent and _looks_like_test_path(candidate.file_path):
            score += test_intent_boost
            candidate.reasons.append("query implies tests; file matches a test-file convention")
        candidate.final_score = round(score, 6)

    ranked = sorted(
        candidates, key=lambda c: (-c.final_score, c.file_path, c.start_line or 0, c.dedup_key)
    )
    return ranked[:top_k]
