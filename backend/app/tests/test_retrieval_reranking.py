"""Unit tests for cross-encoder reranking (pre-Sprint-5 hardening pass)."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.repository import Repository
from app.retrieval.candidates import Candidate
from app.retrieval.reranking import read_candidate_text
from app.retrieval.service import RetrievalService

REPO_ID = uuid.uuid4()


def make_repository(local_path: str) -> Repository:
    return Repository(id=REPO_ID, name="r", local_path=local_path, status="ready")


class TestReadCandidateText:
    def test_reads_exact_line_range(self, tmp_path: Path) -> None:
        source_file = tmp_path / "auth.py"
        source_file.write_text("line1\nline2\nline3\nline4\nline5\n")
        repository = make_repository(str(tmp_path))
        candidate = Candidate(
            dedup_key="a", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="auth.py",
            start_line=2, end_line=4,
        )
        text = read_candidate_text(repository, candidate)
        assert text == "line2\nline3\nline4"

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        repository = make_repository(str(tmp_path))
        candidate = Candidate(
            dedup_key="a", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="does_not_exist.py",
            start_line=1, end_line=2,
        )
        assert read_candidate_text(repository, candidate) is None

    def test_missing_line_range_returns_none(self, tmp_path: Path) -> None:
        repository = make_repository(str(tmp_path))
        candidate = Candidate(dedup_key="a", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="x.py")
        assert read_candidate_text(repository, candidate) is None

    def test_whitespace_only_range_returns_none(self, tmp_path: Path) -> None:
        source_file = tmp_path / "blank.py"
        source_file.write_text("   \n   \n")
        repository = make_repository(str(tmp_path))
        candidate = Candidate(
            dedup_key="a", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="blank.py",
            start_line=1, end_line=2,
        )
        assert read_candidate_text(repository, candidate) is None

    def test_truncates_to_max_chars(self, tmp_path: Path) -> None:
        """A long chunk must be capped — cross-encoder cost scales ~quadratically with length."""
        source_file = tmp_path / "big.py"
        source_file.write_text("x" * 5000 + "\n")
        repository = make_repository(str(tmp_path))
        candidate = Candidate(
            dedup_key="a", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="big.py",
            start_line=1, end_line=1,
        )
        text = read_candidate_text(repository, candidate, max_chars=800)
        assert text is not None
        assert len(text) == 800


class TestRerankingDisabledByDefault:
    def test_default_settings_have_reranking_disabled(self) -> None:
        """Measured cost/benefit (see docs/SPRINT_LOG.md hardening section): not worth it by default."""
        assert Settings().retrieval.reranking_enabled is False


class TestServiceRerank:
    async def test_rerank_reorders_by_cross_encoder_score(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "a.py").write_text("irrelevant content here\n")
        (tmp_path / "b.py").write_text("highly relevant authentication code\n")
        repository = make_repository(str(tmp_path))

        low = Candidate(
            dedup_key="low", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="a.py",
            start_line=1, end_line=1, source_scores={"semantic": 0.9},
        )
        high = Candidate(
            dedup_key="high", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="b.py",
            start_line=1, end_line=1, source_scores={"semantic": 0.5},
        )

        class FakeRerankProvider:
            def rerank(self, query, documents):
                # Score whichever document mentions "authentication" highest,
                # deliberately inverting the fusion-stage order (0.9 vs 0.5).
                return [10.0 if "authentication" in d else -5.0 for d in documents]

        import app.retrieval.service as service_module

        monkeypatch.setattr(service_module, "get_rerank_provider", lambda: FakeRerankProvider())

        service = RetrievalService(session=None, settings=Settings())
        reranked = await service._rerank("auth", repository, [low, high], 4000)

        assert [c.dedup_key for c in reranked] == ["high", "low"]
        assert reranked[0].rerank_score == 10.0
        assert any("reranked" in r for r in reranked[0].reasons)

    async def test_unreadable_candidates_keep_fusion_order(self, tmp_path: Path) -> None:
        repository = make_repository(str(tmp_path))
        first = Candidate(dedup_key="first", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="missing.py")
        second = Candidate(dedup_key="second", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="also_missing.py")

        service = RetrievalService(session=None, settings=Settings())
        result = await service._rerank("q", repository, [first, second], 4000)

        assert [c.dedup_key for c in result] == ["first", "second"]

    async def test_partial_readability_scored_candidates_rank_above_unscored(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "readable.py").write_text("some content\n")
        repository = make_repository(str(tmp_path))

        readable = Candidate(
            dedup_key="readable", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="readable.py",
            start_line=1, end_line=1,
        )
        unreadable = Candidate(dedup_key="unreadable", repository_id=REPO_ID, file_id=uuid.uuid4(), file_path="gone.py")

        class FakeRerankProvider:
            def rerank(self, query, documents):
                return [1.0 for _ in documents]

        import app.retrieval.service as service_module

        monkeypatch.setattr(service_module, "get_rerank_provider", lambda: FakeRerankProvider())

        service = RetrievalService(session=None, settings=Settings())
        result = await service._rerank("q", repository, [unreadable, readable], 4000)

        assert result[0].dedup_key == "readable"
        assert result[1].dedup_key == "unreadable"
