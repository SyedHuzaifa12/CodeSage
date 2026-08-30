"""Evidence assembly helpers — turn deterministic repository facts into ``EvidenceReference`` objects.

Every function here is a pure, deterministic builder over already-parsed
Sprint 2A/2B data (files, symbols, relationships, ``RepositoryIntelligence``)
— nothing here calls the LLM or a database. ``map_verification_to_confidence``
is the one explicit bridge between Sprint 5's AI-answer verification
vocabulary and Sprint 6's report-evidence vocabulary — see ADR-022.
"""
from __future__ import annotations

from app.ai.schemas.verification import VerificationStatus
from app.reports.schemas import EvidenceConfidence, EvidenceReference

_VERIFICATION_TO_CONFIDENCE: dict[VerificationStatus, EvidenceConfidence] = {
    VerificationStatus.SUPPORTED: EvidenceConfidence.DERIVED,
    VerificationStatus.PARTIALLY_SUPPORTED: EvidenceConfidence.PARTIAL,
    VerificationStatus.INSUFFICIENT_EVIDENCE: EvidenceConfidence.INSUFFICIENT_EVIDENCE,
    VerificationStatus.CONTRADICTED: EvidenceConfidence.INSUFFICIENT_EVIDENCE,
}


def map_verification_to_confidence(status: VerificationStatus) -> EvidenceConfidence:
    """Map Sprint 5's citation-verification outcome to a Sprint 6 evidence-confidence label.

    Args:
        status: The verification gate's result for one piece of
            AI-synthesized report prose (reusing
            ``app.ai.engine.verification``'s regex/evidence-set-membership
            mechanics — never a second LLM call, per ADR-020/ADR-023).

    Returns:
        ``DERIVED`` for fully-supported prose (the underlying facts were
        confirmed against evidence), ``PARTIAL`` for partially-supported
        prose, and ``INSUFFICIENT_EVIDENCE`` for both
        ``INSUFFICIENT_EVIDENCE`` and ``CONTRADICTED`` outcomes — a
        contradicted claim must never be presented as fact any more
        than an ungrounded one.
    """
    return _VERIFICATION_TO_CONFIDENCE.get(status, EvidenceConfidence.INSUFFICIENT_EVIDENCE)


def file_evidence(file_path: str, *, description: str | None = None, source: str = "files") -> EvidenceReference:
    """Build a ``VERIFIED`` evidence reference for a single file fact.

    Args:
        file_path: The repository-relative file path.
        description: Optional human-readable note.
        source: The originating data source label.

    Returns:
        An evidence reference pointing at the file.
    """
    return EvidenceReference(source=source, file_path=file_path, description=description)


def symbol_evidence(
    file_path: str, symbol_name: str, *, start_line: int | None = None, end_line: int | None = None,
    description: str | None = None, source: str = "symbols",
) -> EvidenceReference:
    """Build a ``VERIFIED`` evidence reference for a single parsed symbol.

    Args:
        file_path: The file the symbol was parsed from.
        symbol_name: The symbol's name.
        start_line: The symbol's starting line, if known.
        end_line: The symbol's ending line, if known.
        description: Optional human-readable note.
        source: The originating data source label.

    Returns:
        An evidence reference pointing at the symbol.
    """
    return EvidenceReference(
        source=source, file_path=file_path, symbol_name=symbol_name, start_line=start_line, end_line=end_line,
        description=description,
    )


def relationship_evidence(
    source_symbol: str, target_symbol: str, relationship_type: str, *, description: str | None = None,
) -> EvidenceReference:
    """Build a ``DERIVED`` evidence reference for one Knowledge Graph edge.

    A single relationship row is a ``VERIFIED`` database fact in
    isolation, but every report statement built from it (a hotspot
    count, a cycle, an aggregate) is the result of combining/counting
    multiple such rows — so callers that *interpret* relationship data
    (rather than citing one exact edge) should label the containing
    section ``DERIVED``, not ``VERIFIED``. This helper still records the
    exact edge as evidence either way.

    Args:
        source_symbol: The edge's source identifier.
        target_symbol: The edge's target identifier.
        relationship_type: The edge's relationship type (e.g. ``depends_on``).
        description: Optional human-readable note.

    Returns:
        An evidence reference describing the edge.
    """
    return EvidenceReference(
        source="relationships", symbol_name=source_symbol, relationship_type=relationship_type,
        description=description or f"{source_symbol} --{relationship_type}--> {target_symbol}",
    )


def intelligence_evidence(field_name: str, description: str) -> EvidenceReference:
    """Build a ``DERIVED`` evidence reference pointing at a ``RepositoryIntelligence`` field.

    Args:
        field_name: The ``RepositoryIntelligence`` column this fact came from.
        description: A human-readable summary of the fact.

    Returns:
        An evidence reference citing the pre-computed intelligence field.
    """
    return EvidenceReference(source=f"repository_intelligence.{field_name}", description=description)
