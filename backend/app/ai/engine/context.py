"""Evidence Selection + Context Construction (spec §4/§5).

Two distinct concerns kept in one file (matching the pre-existing
``ai/engine/`` skeleton's file layout, which has no separate file for
each): ``select_evidence`` decides *which* retrieval results are worth
using; ``build_context`` turns the selected ones into the deterministic
text block sent to the LLM. Neither function ever aims for "as much
evidence as possible" — both are budget-bounded by ``AISettings``.
"""
from __future__ import annotations

import logging
from typing import Optional

from app.ai.graph.state import EvidenceWithText
from app.ai.schemas.intent import QueryIntent
from app.core.config import AISettings
from app.models.repository import Repository
from app.models.repository_intelligence import RepositoryIntelligence
from app.retrieval.reranking import read_candidate_text
from app.retrieval.schemas import EvidenceResult

logger = logging.getLogger("codesage.ai.engine.context")

# IMPLEMENTATION questions benefit from depth (multiple pieces of one
# file's logic); every other intent benefits more from breadth across
# files — a deliberately small, named exception rather than a tunable
# per-intent table (keeps the diversity rule easy to reason about).
_IMPLEMENTATION_EXTRA_PER_FILE = 2

_PER_ITEM_CHAR_CAP = 2_500  # a single oversized chunk must never consume the whole context budget


def select_evidence(results: list[EvidenceResult], intent: QueryIntent, cfg: AISettings) -> list[EvidenceResult]:
    """Pick the smallest sufficient set of high-quality evidence from already-ranked results.

    Retrieval has already ranked and deduplicated ``results`` — this
    only applies two further, LLM-context-specific constraints:
    a per-file diversity cap (so a handful of chunks from one file
    don't crowd out cross-file synthesis) and a hard item-count ceiling.

    Args:
        results: Retrieval's ranked, deduplicated results (best first).
        intent: The classified query intent.
        cfg: AI Engine settings (evidence budget).

    Returns:
        The selected subset, in the same (already-ranked) order.
    """
    max_per_file = cfg.max_evidence_per_file
    if intent == QueryIntent.IMPLEMENTATION:
        max_per_file += _IMPLEMENTATION_EXTRA_PER_FILE

    selected: list[EvidenceResult] = []
    per_file_count: dict[str, int] = {}
    for item in results:
        if per_file_count.get(item.file_path, 0) >= max_per_file:
            continue
        selected.append(item)
        per_file_count[item.file_path] = per_file_count.get(item.file_path, 0) + 1
        if len(selected) >= cfg.max_evidence_items:
            break

    logger.debug("Evidence selection: %d of %d candidates kept (max_items=%d, max_per_file=%d)", len(selected), len(results), cfg.max_evidence_items, max_per_file)
    return selected


def _format_evidence_block(index: int, item: EvidenceResult, text: Optional[str]) -> str:
    """Format one evidence item as a clearly-delimited block with its metadata header."""
    location = item.file_path
    if item.symbol_name:
        location += f" ({item.symbol_type or 'symbol'}: {item.symbol_name})"
    if item.start_line is not None and item.end_line is not None:
        location += f", lines {item.start_line}-{item.end_line}"

    header = f"[Evidence {index}] {location} — score {item.final_score:.2f} (source: {', '.join(item.sources)})"
    if not text:
        return f"{header}\n(source text unavailable)"
    return f"{header}\n```\n{text}\n```"


def build_context(
    repository: Repository, evidence: list[EvidenceResult], intent: QueryIntent, cfg: AISettings,
    intelligence: Optional[RepositoryIntelligence] = None,
) -> tuple[str, list[EvidenceWithText]]:
    """Build the deterministic, budget-bounded context text sent to the LLM.

    Args:
        repository: The owning repository (for its local clone path —
            source text is read from disk, never persisted; see Sprint 3).
        evidence: The already-selected evidence (see ``select_evidence``).
        intent: The classified query intent.
        cfg: AI Engine settings (context character budget).
        intelligence: The repository's Sprint 2B intelligence summary —
            included as an additional block only for
            ``ARCHITECTURE_OVERVIEW`` questions (reusing the same
            cross-module read ``RetrievalService`` itself already
            performs for entry-point/hotspot boosts).

    Returns:
        ``(context_text, enriched_evidence)`` — the formatted text
        ready for the prompt, and the evidence list enriched with the
        actual source text that was included (for citation verification
        and for the response's evidence list).
    """
    blocks: list[str] = []
    enriched: list[EvidenceWithText] = []
    remaining_budget = cfg.max_context_chars

    if intent == QueryIntent.ARCHITECTURE_OVERVIEW and intelligence is not None:
        summary = (
            f"[Repository Summary] languages={intelligence.languages}, "
            f"entry_points={intelligence.entry_points}, "
            f"architecture_hints={intelligence.architecture_hints}"
        )
        blocks.append(summary)
        remaining_budget -= len(summary)

    for index, item in enumerate(evidence, start=1):
        if remaining_budget <= 0:
            break
        per_item_cap = min(_PER_ITEM_CHAR_CAP, remaining_budget)
        text = read_candidate_text(repository, item, max_chars=per_item_cap)
        block = _format_evidence_block(index, item, text)
        if len(block) > remaining_budget:
            break  # keep whole evidence items only — never cut one mid-block
        blocks.append(block)
        remaining_budget -= len(block)
        enriched.append(
            EvidenceWithText(
                file_path=item.file_path, symbol_name=item.symbol_name, symbol_type=item.symbol_type,
                start_line=item.start_line, end_line=item.end_line, retrieval_score=item.final_score,
                retrieval_sources=item.sources, text=text,
            )
        )

    context_text = "\n\n".join(blocks) if blocks else "(no repository evidence retrieved)"
    return context_text, enriched
