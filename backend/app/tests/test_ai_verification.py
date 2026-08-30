"""Unit tests for the deterministic verification gate (Sprint 5) — the primary hallucination defense."""
from __future__ import annotations

import uuid

from app.ai.engine.verification import pre_check_evidence_sufficiency, verify_answer
from app.ai.graph.state import EvidenceWithText
from app.ai.schemas.verification import VerificationStatus
from app.core.config import Settings
from app.retrieval.schemas import EvidenceResult

REPO = uuid.uuid4()


def make_evidence_result(file_path: str, score: float) -> EvidenceResult:
    return EvidenceResult(
        rank=1, final_score=score, repository_id=REPO, file_id=uuid.uuid4(), file_path=file_path,
        chunk_id=None, symbol_id=None, symbol_name=None, qualified_name=None, symbol_type=None,
        start_line=1, end_line=10, language="Python", sources=["semantic"], source_scores=[], reasons=[],
    )


def make_evidence_with_text(file_path: str, symbol_name: str | None = None, start_line: int = 1, end_line: int = 30) -> EvidenceWithText:
    return EvidenceWithText(
        file_path=file_path, symbol_name=symbol_name, symbol_type="function" if symbol_name else None,
        start_line=start_line, end_line=end_line, retrieval_score=0.8, retrieval_sources=["semantic"],
        text="def authenticate_user(): pass",
    )


class TestPreCheckEvidenceSufficiency:
    def test_empty_evidence_is_insufficient(self) -> None:
        cfg = Settings().ai
        result = pre_check_evidence_sufficiency([], cfg)
        assert result is not None
        assert result.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_low_scoring_evidence_is_insufficient(self) -> None:
        cfg = Settings().ai
        result = pre_check_evidence_sufficiency([make_evidence_result("x.py", 0.01)], cfg)
        assert result is not None
        assert result.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_high_scoring_evidence_passes(self) -> None:
        cfg = Settings().ai
        result = pre_check_evidence_sufficiency([make_evidence_result("x.py", 0.9)], cfg)
        assert result is None


class TestVerifyAnswer:
    def test_valid_file_citation_is_supported(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py")]
        result = verify_answer("Authentication is implemented in app/auth.py.", evidence)
        assert result.status == VerificationStatus.SUPPORTED

    def test_fabricated_file_path_is_contradicted(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py")]
        result = verify_answer("Authentication is implemented in app/nonexistent_module.py.", evidence)
        assert result.status == VerificationStatus.CONTRADICTED

    def test_valid_symbol_call_citation_is_supported(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py", symbol_name="authenticate_user")]
        result = verify_answer("The authenticate_user() function handles login.", evidence)
        assert result.status == VerificationStatus.SUPPORTED

    def test_fabricated_symbol_is_contradicted(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py", symbol_name="authenticate_user")]
        result = verify_answer("The verifyMagicToken() function handles login.", evidence)
        assert result.status == VerificationStatus.CONTRADICTED

    def test_valid_line_range_is_supported(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py", start_line=10, end_line=50)]
        result = verify_answer("See app/auth.py, lines 15-20.", evidence)
        assert result.status == VerificationStatus.SUPPORTED

    def test_fabricated_line_range_is_contradicted(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py", start_line=10, end_line=50)]
        # No file path cited here (co-citing a valid path would legitimately earn
        # PARTIALLY_SUPPORTED — see the mixed-citation test below) — this isolates
        # the line-range check on its own.
        result = verify_answer("See lines 900-950 for the implementation.", evidence)
        assert result.status == VerificationStatus.CONTRADICTED

    def test_fabricated_line_range_with_valid_path_is_partially_supported(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py", start_line=10, end_line=50)]
        result = verify_answer("See app/auth.py, lines 900-950.", evidence)
        assert result.status == VerificationStatus.PARTIALLY_SUPPORTED

    def test_mixed_valid_and_invalid_citations_is_partially_supported(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py")]
        result = verify_answer("See app/auth.py and also app/fabricated.py.", evidence)
        assert result.status == VerificationStatus.PARTIALLY_SUPPORTED

    def test_no_citations_with_evidence_is_supported(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py")]
        result = verify_answer("This repository is written in Python.", evidence)
        assert result.status == VerificationStatus.SUPPORTED

    def test_explicit_decline_is_insufficient_evidence(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py")]
        result = verify_answer("I don't have enough information to answer this question.", evidence)
        assert result.status == VerificationStatus.INSUFFICIENT_EVIDENCE

    def test_never_raises_on_empty_evidence(self) -> None:
        result = verify_answer("See app/auth.py.", [])
        assert result.status == VerificationStatus.CONTRADICTED

    def test_is_acceptable_property(self) -> None:
        evidence = [make_evidence_with_text("app/auth.py")]
        supported = verify_answer("See app/auth.py.", evidence)
        contradicted = verify_answer("See app/fake.py.", evidence)
        assert supported.is_acceptable is True
        assert contradicted.is_acceptable is False
