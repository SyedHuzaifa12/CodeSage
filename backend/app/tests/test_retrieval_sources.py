"""Unit tests for each retrieval source's candidate-shaping logic (Sprint 4).

Each source's actual data access (Qdrant client, SQL queries) is
replaced with a fake/monkeypatched stand-in — these tests exercise only
"given these raw hits, are the resulting Candidates correct", not the
underlying infrastructure calls (covered by the live Docker validation).
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.models.relationship import Relationship
from app.models.symbol import Symbol
from app.retrieval import lexical, semantic, structural
from app.retrieval.candidates import Candidate
from app.retrieval.utils import analyze_query

REPO = uuid.uuid4()


class FakeEmbeddingProvider:
    dimension = 4
    version = "fake:1"

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class FakeQdrantClient:
    def __init__(self, points: list) -> None:
        self._points = points

    async def query_points(self, **kwargs):
        return SimpleNamespace(points=self._points)


def make_symbol(*, name: str, qualified_name: str, symbol_type: str = "class", file_id=None) -> Symbol:
    return Symbol(
        id=uuid.uuid4(), file_id=file_id or uuid.uuid4(), name=name, qualified_name=qualified_name,
        symbol_type=symbol_type, visibility="public", start_line=1, end_line=10,
    )


class TestSemanticCandidates:
    async def test_empty_query_returns_no_candidates(self) -> None:
        candidates = await semantic.get_semantic_candidates(
            qdrant_client=FakeQdrantClient([]), provider=FakeEmbeddingProvider(),
            repository_id=REPO, query="   ", limit=10,
        )
        assert candidates == []

    async def test_hits_are_shaped_into_candidates(self) -> None:
        file_id = str(uuid.uuid4())
        symbol_id = str(uuid.uuid4())
        hit = SimpleNamespace(
            id=str(uuid.uuid4()), score=0.87,
            payload={
                "file_id": file_id, "symbol_id": symbol_id, "file_path": "app/auth.py",
                "start_line": 5, "end_line": 20, "language": "Python",
            },
        )
        candidates = await semantic.get_semantic_candidates(
            qdrant_client=FakeQdrantClient([hit]), provider=FakeEmbeddingProvider(),
            repository_id=REPO, query="authentication", limit=10,
        )
        assert len(candidates) == 1
        assert candidates[0].source_scores["semantic"] == 0.87
        assert candidates[0].file_path == "app/auth.py"
        assert candidates[0].dedup_key == f"chunk:{hit.id}"

    async def test_point_missing_file_id_is_skipped(self) -> None:
        hit = SimpleNamespace(id=str(uuid.uuid4()), score=0.5, payload={"file_path": "x.py"})
        candidates = await semantic.get_semantic_candidates(
            qdrant_client=FakeQdrantClient([hit]), provider=FakeEmbeddingProvider(),
            repository_id=REPO, query="q", limit=10,
        )
        assert candidates == []

    async def test_hits_below_min_score_are_filtered_out(self) -> None:
        low = SimpleNamespace(
            id=str(uuid.uuid4()), score=0.3, payload={"file_id": str(uuid.uuid4()), "file_path": "x.py"}
        )
        high = SimpleNamespace(
            id=str(uuid.uuid4()), score=0.8, payload={"file_id": str(uuid.uuid4()), "file_path": "y.py"}
        )
        candidates = await semantic.get_semantic_candidates(
            qdrant_client=FakeQdrantClient([low, high]), provider=FakeEmbeddingProvider(),
            repository_id=REPO, query="q", limit=10, min_score=0.5,
        )
        assert len(candidates) == 1
        assert candidates[0].file_path == "y.py"

    async def test_min_score_zero_keeps_every_hit(self) -> None:
        hit = SimpleNamespace(id=str(uuid.uuid4()), score=0.01, payload={"file_id": str(uuid.uuid4()), "file_path": "x.py"})
        candidates = await semantic.get_semantic_candidates(
            qdrant_client=FakeQdrantClient([hit]), provider=FakeEmbeddingProvider(),
            repository_id=REPO, query="q", limit=10, min_score=0.0,
        )
        assert len(candidates) == 1


class TestLexicalCandidates:
    async def test_no_identifier_tokens_returns_no_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = False

        async def fail_if_called(*args, **kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr(lexical, "search_symbols_by_token", fail_if_called)
        analysis = analyze_query("where is the implementation")  # all stopwords, no tokens
        candidates = await lexical.get_lexical_candidates(
            session=None, repository_id=REPO, analysis=analysis, limit=10, min_similarity=0.2
        )
        assert candidates == []
        assert called is False

    async def test_symbol_and_file_hits_both_become_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        symbol = make_symbol(name="AuthService", qualified_name="app.auth.AuthService")

        async def fake_search_symbols(session, repository_id, token, limit, min_similarity):
            return [(symbol, "app/auth.py", 1.0)]

        async def fake_search_files(session, repository_id, token, limit, min_similarity):
            return [(SimpleNamespace(id=uuid.uuid4(), path="app/auth_config.py", language="Python"), 0.6)]

        monkeypatch.setattr(lexical, "search_symbols_by_token", fake_search_symbols)
        monkeypatch.setattr(lexical, "search_files_by_token", fake_search_files)

        analysis = analyze_query("AuthService")
        candidates = await lexical.get_lexical_candidates(
            session=None, repository_id=REPO, analysis=analysis, limit=10, min_similarity=0.2
        )
        assert len(candidates) == 2
        symbol_candidate = next(c for c in candidates if c.symbol_id is not None)
        assert symbol_candidate.source_scores["lexical"] == 1.0
        assert symbol_candidate.qualified_name == "app.auth.AuthService"


class TestStructuralCandidates:
    async def test_no_seed_qualified_names_returns_no_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = False

        async def fail_if_called(*args, **kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr(structural, "get_relationships_touching", fail_if_called)
        seeds = [Candidate(dedup_key="k", repository_id=REPO, file_id=uuid.uuid4(), file_path="x.py")]
        candidates = await structural.get_structural_candidates(
            session=None, repository_id=REPO, seed_candidates=seeds, max_seeds=5, max_related=20
        )
        assert candidates == []
        assert called is False

    async def test_one_hop_expansion_produces_scored_candidates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seed = Candidate(
            dedup_key="seed", repository_id=REPO, file_id=uuid.uuid4(), file_path="app/service.py",
            qualified_name="app.service.OrderService",
        )
        related_symbol = make_symbol(name="PaymentRepository", qualified_name="app.repo.PaymentRepository")
        relationship = Relationship(
            repository_id=REPO, source_symbol="app.service.OrderService",
            target_symbol="app.repo.PaymentRepository", relationship_type="calls",
        )

        async def fake_relationships(session, repository_id, qualified_names, limit):
            assert qualified_names == ["app.service.OrderService"]
            return [relationship]

        async def fake_resolve(session, repository_id, qualified_names, limit):
            assert qualified_names == ["app.repo.PaymentRepository"]
            return [(related_symbol, "app/repo.py")]

        monkeypatch.setattr(structural, "get_relationships_touching", fake_relationships)
        monkeypatch.setattr(structural, "get_symbols_by_qualified_names", fake_resolve)

        candidates = await structural.get_structural_candidates(
            session=None, repository_id=REPO, seed_candidates=[seed], max_seeds=5, max_related=20
        )
        assert len(candidates) == 1
        assert candidates[0].qualified_name == "app.repo.PaymentRepository"
        assert candidates[0].source_scores["structural"] == 0.70  # "calls" weight
        assert "calls" in candidates[0].reasons[0]

    async def test_seed_symbols_are_not_returned_as_their_own_related_symbol(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A relationship between two seeds must not re-surface a seed as 'related'."""
        seed_a = Candidate(
            dedup_key="a", repository_id=REPO, file_id=uuid.uuid4(), file_path="a.py", qualified_name="pkg.A",
        )
        seed_b = Candidate(
            dedup_key="b", repository_id=REPO, file_id=uuid.uuid4(), file_path="b.py", qualified_name="pkg.B",
        )
        relationship = Relationship(
            repository_id=REPO, source_symbol="pkg.A", target_symbol="pkg.B", relationship_type="calls"
        )

        async def fake_relationships(session, repository_id, qualified_names, limit):
            return [relationship]

        resolve_called_with: list = []

        async def fake_resolve(session, repository_id, qualified_names, limit):
            resolve_called_with.extend(qualified_names)
            return []

        monkeypatch.setattr(structural, "get_relationships_touching", fake_relationships)
        monkeypatch.setattr(structural, "get_symbols_by_qualified_names", fake_resolve)

        await structural.get_structural_candidates(
            session=None, repository_id=REPO, seed_candidates=[seed_a, seed_b], max_seeds=5, max_related=20
        )
        assert resolve_called_with == []
