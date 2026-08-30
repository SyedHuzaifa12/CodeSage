"""Query normalization, identifier tokenization, and latency instrumentation.

Kept dependency-free (no DB/Qdrant/Redis imports) so every function
here is trivially unit-testable in isolation.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field

# A query like "Where is authentication implemented?" must not run a
# lexical search for "where"/"is"/"implemented" — this small stopword
# list keeps identifier extraction focused on words that could plausibly
# be a symbol/file name. Deliberately small and English-only: this is a
# retrieval-quality heuristic, not a linguistic component.
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "where", "what", "which", "who", "whom", "how", "why", "when",
        "do", "does", "did", "doing", "done",
        "in", "on", "at", "of", "for", "to", "from", "with", "by", "about",
        "and", "or", "not", "no", "this", "that", "these", "those",
        "it", "its", "there", "here", "should", "would", "could", "can",
        "implemented", "implement", "implements", "implementation",
        "related", "relate", "relates", "likely", "made", "make", "code",
    }
)

_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class QueryAnalysis:
    """A normalized query, split into the pieces each retrieval source needs."""

    raw: str
    normalized: str
    identifier_tokens: list[str] = field(default_factory=list)


def analyze_query(query: str, max_tokens: int = 6) -> QueryAnalysis:
    """Normalize a free-text query and extract candidate identifier tokens.

    The raw query (whitespace-collapsed) is what semantic search embeds
    — natural language works fine there. ``identifier_tokens`` is what
    lexical search runs against symbol/file names — a general sentence
    like "where is authentication implemented" is useless as an exact
    substring match, but the extracted token "authentication" is not.

    Args:
        query: The raw user query.
        max_tokens: Maximum identifier tokens to return (bounds lexical
            search fan-out — see ``RetrievalSettings.lexical_tokens_per_query``).

    Returns:
        The parsed query, or an all-empty analysis for blank input.
    """
    normalized = " ".join(query.strip().split())
    if not normalized:
        return QueryAnalysis(raw=query, normalized="")

    seen: set[str] = set()
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        word = match.group(0)
        lowered = word.lower()
        if len(word) < 3 or lowered in _STOPWORDS or lowered in seen:
            continue
        seen.add(lowered)
        tokens.append(word)
        if len(tokens) >= max_tokens:
            break

    return QueryAnalysis(raw=query, normalized=normalized, identifier_tokens=tokens)


def cache_key(
    *, repository_id: str, normalized_query: str, top_k: int, sources: tuple[str, ...], corpus_version: str,
    reranking_enabled: bool = False,
) -> str:
    """Build a Redis key covering every input that affects retrieval correctness.

    ``corpus_version`` (derived from the repository's knowledge-index
    state — see ``retrieval/cache.py``) ties the key to a specific
    indexed snapshot: a re-index changes it, so a stale cached result
    from before a re-index is simply never looked up again (naturally
    expires via TTL rather than requiring an active purge — the same
    pattern Sprint 3 uses for the embedding cache).

    Args:
        repository_id: The repository being queried (never omit —
            cross-repository cache leakage would be a correctness bug).
        normalized_query: The whitespace-normalized query text.
        top_k: Requested result count.
        sources: The retrieval sources enabled for this query, sorted.
        corpus_version: A string identifying the indexed data snapshot.
        reranking_enabled: The *effective* reranking flag for this
            query (post any per-request override) — reranking changes
            the actual result order, so it must be part of the key or
            an A/B comparison would silently read the other side's
            cached answer.

    Returns:
        A stable cache key.
    """
    digest_input = "|".join(
        [
            repository_id, normalized_query.lower(), str(top_k), ",".join(sorted(sources)), corpus_version,
            f"rerank={reranking_enabled}",
        ]
    )
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    return f"codesage:retrieval:{repository_id}:{digest}"


class StageTimer:
    """Accumulates named stage durations for a single retrieval request.

    Not thread-safe by design — one instance is created per request and
    never shared, matching how every other timing block in this
    codebase (Sprint 2B/3's ``time.perf_counter()`` pattern) is used.
    """

    def __init__(self) -> None:
        self._durations_ms: dict[str, int] = {}

    def stage(self, name: str) -> "_StageContext":
        """Return a context manager that records ``name``'s wall-clock duration.

        Args:
            name: The stage's label (e.g. ``"semantic"``, ``"fusion"``).
        """
        return _StageContext(self, name)

    def record(self, name: str, milliseconds: int) -> None:
        """Record a duration measured elsewhere (e.g. inside a gathered coroutine).

        Args:
            name: The stage's label.
            milliseconds: Elapsed time in whole milliseconds.
        """
        self._durations_ms[name] = self._durations_ms.get(name, 0) + milliseconds

    def as_dict(self) -> dict[str, int]:
        """Return every recorded stage's duration.

        Returns:
            A copy of the stage-name to milliseconds mapping.
        """
        return dict(self._durations_ms)


class _StageContext:
    def __init__(self, timer: StageTimer, name: str) -> None:
        self._timer = timer
        self._name = name
        self._started = 0.0

    def __enter__(self) -> "_StageContext":
        self._started = time.perf_counter()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._timer.record(self._name, int((time.perf_counter() - self._started) * 1000))
