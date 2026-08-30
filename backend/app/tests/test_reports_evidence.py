"""Unit tests for evidence assembly and the verification->confidence mapping (ADR-022)."""
from __future__ import annotations

from app.ai.schemas.verification import VerificationStatus
from app.reports.evidence import (
    file_evidence,
    intelligence_evidence,
    map_verification_to_confidence,
    relationship_evidence,
    symbol_evidence,
)
from app.reports.schemas import EvidenceConfidence


class TestMapVerificationToConfidence:
    def test_supported_maps_to_derived(self) -> None:
        assert map_verification_to_confidence(VerificationStatus.SUPPORTED) == EvidenceConfidence.DERIVED

    def test_partially_supported_maps_to_partial(self) -> None:
        assert map_verification_to_confidence(VerificationStatus.PARTIALLY_SUPPORTED) == EvidenceConfidence.PARTIAL

    def test_insufficient_evidence_maps_to_insufficient_evidence(self) -> None:
        assert map_verification_to_confidence(VerificationStatus.INSUFFICIENT_EVIDENCE) == EvidenceConfidence.INSUFFICIENT_EVIDENCE

    def test_contradicted_maps_to_insufficient_evidence(self) -> None:
        """A contradicted claim must never be presented as fact any more than an ungrounded one."""
        assert map_verification_to_confidence(VerificationStatus.CONTRADICTED) == EvidenceConfidence.INSUFFICIENT_EVIDENCE


class TestEvidenceBuilders:
    def test_file_evidence_carries_path(self) -> None:
        ref = file_evidence("app/main.py", description="entry point")
        assert ref.file_path == "app/main.py"
        assert ref.description == "entry point"
        assert ref.source == "files"

    def test_symbol_evidence_carries_lines(self) -> None:
        ref = symbol_evidence("app/auth.py", "AuthService", start_line=1, end_line=30)
        assert ref.symbol_name == "AuthService"
        assert ref.start_line == 1 and ref.end_line == 30

    def test_relationship_evidence_carries_type(self) -> None:
        ref = relationship_evidence("app.a", "app.b", "depends_on")
        assert ref.relationship_type == "depends_on"
        assert "app.a" in ref.description and "app.b" in ref.description

    def test_intelligence_evidence_carries_field_name(self) -> None:
        ref = intelligence_evidence("dependency_hotspots", "app.core has 5 dependents")
        assert ref.source == "repository_intelligence.dependency_hotspots"
