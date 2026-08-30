"""Verification Gate (spec §8) — deterministic checks only, never a second LLM call.

The primary defense against hallucination: every file path, function
call, and line-range citation the LLM's answer contains is checked
against the actual evidence set it was given. A citation that doesn't
correspond to real evidence means the LLM fabricated it — that is
exactly what this module exists to catch, deterministically.
"""
from __future__ import annotations

import re

from app.ai.graph.state import EvidenceWithText
from app.ai.schemas.verification import CitationCheck, VerificationResult, VerificationStatus
from app.core.config import AISettings
from app.retrieval.schemas import EvidenceResult

# Deliberately a whitelist of common code/config/doc extensions rather
# than "any word.word" — avoids false-positive "paths" like "e.g." or
# "i.e." while still catching every extension this project's own
# Tree-sitter/Knowledge pipeline recognizes (see
# app/ingestion/utils.py::EXTENSION_LANGUAGE_MAP) plus a few common
# non-code extensions the LLM might legitimately cite (README, config).
_FILE_PATH_RE = re.compile(
    r"\b[\w][\w\-./]*\.(?:py|pyi|js|jsx|mjs|cjs|ts|tsx|java|kt|go|rs|rb|php|c|h|cpp|cc|cs|json|ya?ml|toml|"
    r"md|mdx|txt|cfg|ini|sql|html?|css|xml|sh)\b"
)
_SYMBOL_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(\)")
_LINE_RANGE_RE = re.compile(r"\bline[s]?\s+(\d+)(?:\s*(?:[-–—]|to)\s*(\d+))?\b", re.IGNORECASE)

_DECLINE_PHRASES = (
    "insufficient evidence", "not enough evidence", "not enough information", "cannot determine",
    "can't determine", "don't have enough", "do not have enough", "no evidence", "unable to determine",
    "cannot answer", "can't answer", "the evidence does not", "the evidence doesn't",
)


def pre_check_evidence_sufficiency(evidence: list[EvidenceResult], cfg: AISettings) -> VerificationResult | None:
    """Short-circuit to ``INSUFFICIENT_EVIDENCE`` before spending an LLM call, if evidence is too sparse.

    Args:
        evidence: The selected evidence (post ``select_evidence``).
        cfg: AI Engine settings (relevance floor).

    Returns:
        A pre-built ``INSUFFICIENT_EVIDENCE`` result if evidence is
        empty or every item scores below the configured floor;
        ``None`` otherwise (proceed to reasoning normally).
    """
    if not evidence:
        return VerificationResult(status=VerificationStatus.INSUFFICIENT_EVIDENCE, reasons=["No retrieval evidence was found for this query."])
    if max(item.final_score for item in evidence) < cfg.min_evidence_relevance:
        return VerificationResult(
            status=VerificationStatus.INSUFFICIENT_EVIDENCE,
            reasons=[f"The best-matching evidence scored below the minimum relevance floor ({cfg.min_evidence_relevance})."],
        )
    return None


def verify_answer(answer_text: str, evidence: list[EvidenceWithText]) -> VerificationResult:
    """Check every citation in an answer against the evidence it was given.

    Args:
        answer_text: The LLM's raw answer text.
        evidence: The exact evidence set the LLM was shown (already
            enriched with source text — see ``ai/engine/context.py``).

    Returns:
        The verification outcome. Never raises — an answer with zero
        extractable citations is treated as ``SUPPORTED`` (not every
        valid answer, e.g. a language/summary question, needs a
        citation) unless the answer text itself reads as a decline,
        in which case it's honestly reported as ``INSUFFICIENT_EVIDENCE``.
    """
    evidence_paths = {item["file_path"] for item in evidence}
    evidence_symbols = {item["symbol_name"] for item in evidence if item.get("symbol_name")}
    evidence_line_ranges = [
        (item["file_path"], item["start_line"], item["end_line"])
        for item in evidence
        if item.get("start_line") is not None and item.get("end_line") is not None
    ]

    checks: list[CitationCheck] = []

    for match in _FILE_PATH_RE.finditer(answer_text):
        cited_path = match.group(0)
        valid = any(cited_path == p or p.endswith("/" + cited_path) or cited_path.endswith("/" + p) for p in evidence_paths)
        checks.append(CitationCheck(raw_text=cited_path, kind="file_path", valid=valid, reason="matches evidence file path" if valid else "no evidence file has this path"))

    for match in _SYMBOL_CALL_RE.finditer(answer_text):
        cited_symbol = match.group(1)
        valid = cited_symbol in evidence_symbols
        checks.append(CitationCheck(raw_text=f"{cited_symbol}()", kind="symbol", valid=valid, reason="matches an evidence symbol" if valid else "no evidence symbol has this name"))

    for match in _LINE_RANGE_RE.finditer(answer_text):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        valid = any(evidence_start <= start and end <= evidence_end for _, evidence_start, evidence_end in evidence_line_ranges)
        checks.append(CitationCheck(raw_text=match.group(0), kind="line_range", valid=valid, reason="within an evidence line range" if valid else "outside every evidence item's actual line range"))

    if not checks:
        if any(phrase in answer_text.lower() for phrase in _DECLINE_PHRASES):
            return VerificationResult(status=VerificationStatus.INSUFFICIENT_EVIDENCE, reasons=["The answer itself states the evidence was insufficient."])
        return VerificationResult(status=VerificationStatus.SUPPORTED, citation_checks=[], reasons=["No file/symbol/line citations to verify; answer contains no unverifiable claims of that kind."])

    invalid = [c for c in checks if not c.valid]
    if not invalid:
        return VerificationResult(status=VerificationStatus.SUPPORTED, citation_checks=checks, reasons=[f"All {len(checks)} citation(s) verified against evidence."])
    if len(invalid) == len(checks):
        return VerificationResult(
            status=VerificationStatus.CONTRADICTED, citation_checks=checks,
            reasons=[f"All {len(invalid)} citation(s) reference files/symbols/lines not present in the retrieved evidence."],
        )
    return VerificationResult(
        status=VerificationStatus.PARTIALLY_SUPPORTED, citation_checks=checks,
        reasons=[f"{len(checks) - len(invalid)} of {len(checks)} citation(s) verified; {len(invalid)} could not be confirmed against evidence."],
    )
