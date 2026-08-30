"""Verification gate contracts — result shape, not the checker itself.

The checker lives in ``ai/engine/verification.py``; deliberately no
LLM-produced field here — every field is derived from deterministic
comparison against the evidence set (spec §8: "do not allow
verification to become another uncontrolled LLM hallucination layer").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class VerificationStatus(str, Enum):
    """How well an answer's claims are supported by the retrieved evidence."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTED = "contradicted"


@dataclass
class CitationCheck:
    """One citation extracted from the answer text, and whether it checked out."""

    raw_text: str
    kind: str  # "file_path" | "symbol" | "line_range"
    valid: bool
    reason: str


@dataclass
class VerificationResult:
    """The full outcome of verifying one answer against its evidence."""

    status: VerificationStatus
    citation_checks: list[CitationCheck] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def is_acceptable(self) -> bool:
        """Whether this result can be returned as-is (no retry/downgrade needed).

        Returns:
            ``True`` for ``SUPPORTED``/``PARTIALLY_SUPPORTED`` — a
            partially-supported answer is still returned (with its
            unsupported parts stripped by the formatter), never
            silently upgraded to look fully supported.
        """
        return self.status in (VerificationStatus.SUPPORTED, VerificationStatus.PARTIALLY_SUPPORTED)
