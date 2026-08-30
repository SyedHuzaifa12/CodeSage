"""Unit tests for evidence selection and context construction (Sprint 5)."""
from __future__ import annotations

import uuid
from pathlib import Path

from app.ai.engine.context import build_context, select_evidence
from app.ai.schemas.intent import QueryIntent
from app.core.config import Settings
from app.models.repository import Repository
from app.retrieval.schemas import EvidenceResult

REPO = uuid.uuid4()


def make_evidence(rank: int, file_path: str, score: float, **kwargs) -> EvidenceResult:
    return EvidenceResult(
        rank=rank, final_score=score, repository_id=REPO, file_id=uuid.uuid4(), file_path=file_path,
        chunk_id=None, symbol_id=None, symbol_name=kwargs.get("symbol_name"), qualified_name=None,
        symbol_type=kwargs.get("symbol_type"), start_line=kwargs.get("start_line", 1), end_line=kwargs.get("end_line", 5),
        language="Python", sources=["semantic"], source_scores=[], reasons=[],
    )


class TestSelectEvidence:
    def test_respects_max_items(self) -> None:
        cfg = Settings().ai
        results = [make_evidence(i, f"file_{i}.py", 1.0 - i * 0.01) for i in range(20)]
        selected = select_evidence(results, QueryIntent.GENERAL, cfg)
        assert len(selected) <= cfg.max_evidence_items

    def test_diversity_cap_limits_items_per_file(self) -> None:
        cfg = Settings().ai
        results = [make_evidence(i, "same_file.py", 1.0 - i * 0.01) for i in range(10)]
        selected = select_evidence(results, QueryIntent.GENERAL, cfg)
        assert len(selected) == cfg.max_evidence_per_file

    def test_implementation_intent_allows_more_depth_per_file(self) -> None:
        cfg = Settings().ai
        results = [make_evidence(i, "same_file.py", 1.0 - i * 0.01) for i in range(10)]
        general_selected = select_evidence(results, QueryIntent.GENERAL, cfg)
        impl_selected = select_evidence(results, QueryIntent.IMPLEMENTATION, cfg)
        assert len(impl_selected) > len(general_selected)

    def test_preserves_rank_order(self) -> None:
        cfg = Settings().ai
        results = [make_evidence(i, f"file_{i}.py", 1.0 - i * 0.01) for i in range(3)]
        selected = select_evidence(results, QueryIntent.GENERAL, cfg)
        assert [item.file_path for item in selected] == ["file_0.py", "file_1.py", "file_2.py"]

    def test_empty_results_returns_empty(self) -> None:
        cfg = Settings().ai
        assert select_evidence([], QueryIntent.GENERAL, cfg) == []


class TestBuildContext:
    def test_reads_actual_source_text(self, tmp_path: Path) -> None:
        (tmp_path / "auth.py").write_text("def login():\n    return True\n")
        repository = Repository(id=REPO, name="r", local_path=str(tmp_path), status="ready")
        evidence = [make_evidence(1, "auth.py", 0.9, symbol_name="login", start_line=1, end_line=2)]
        cfg = Settings().ai

        context_text, enriched = build_context(repository, evidence, QueryIntent.GENERAL, cfg)

        assert "def login():" in context_text
        assert "auth.py" in context_text
        assert len(enriched) == 1
        assert enriched[0]["text"] is not None

    def test_missing_file_does_not_crash(self, tmp_path: Path) -> None:
        repository = Repository(id=REPO, name="r", local_path=str(tmp_path), status="ready")
        evidence = [make_evidence(1, "does_not_exist.py", 0.9)]
        cfg = Settings().ai

        context_text, enriched = build_context(repository, evidence, QueryIntent.GENERAL, cfg)

        assert "source text unavailable" in context_text
        assert len(enriched) == 1
        assert enriched[0]["text"] is None

    def test_empty_evidence_produces_placeholder_context(self, tmp_path: Path) -> None:
        repository = Repository(id=REPO, name="r", local_path=str(tmp_path), status="ready")
        cfg = Settings().ai
        context_text, enriched = build_context(repository, [], QueryIntent.GENERAL, cfg)
        assert enriched == []
        assert "no repository evidence" in context_text.lower()

    def test_respects_context_char_budget(self, tmp_path: Path) -> None:
        (tmp_path / "big.py").write_text("x" * 5000 + "\n")
        (tmp_path / "big2.py").write_text("y" * 5000 + "\n")
        repository = Repository(id=REPO, name="r", local_path=str(tmp_path), status="ready")
        evidence = [
            make_evidence(1, "big.py", 0.9, start_line=1, end_line=1),
            make_evidence(2, "big2.py", 0.8, start_line=1, end_line=1),
        ]
        cfg = Settings()
        cfg.ai.max_context_chars = 1000

        context_text, enriched = build_context(repository, evidence, QueryIntent.GENERAL, cfg.ai)

        assert len(context_text) <= 1000 + 500  # generous slack for headers/delimiters
        assert len(enriched) <= 1

    def test_architecture_overview_includes_repository_summary(self, tmp_path: Path) -> None:
        from app.models.repository_intelligence import RepositoryIntelligence

        repository = Repository(id=REPO, name="r", local_path=str(tmp_path), status="ready")
        intelligence = RepositoryIntelligence(
            repository_id=REPO, languages={"Python": 10}, entry_points=["app.py"],
            architecture_hints=["Multi-language repository"],
        )
        cfg = Settings().ai

        context_text, _ = build_context(repository, [], QueryIntent.ARCHITECTURE_OVERVIEW, cfg, intelligence)

        assert "Repository Summary" in context_text
        assert "app.py" in context_text
