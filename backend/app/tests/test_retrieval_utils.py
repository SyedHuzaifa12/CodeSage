"""Unit tests for query normalization/tokenization and cache-key correctness (Sprint 4)."""
from __future__ import annotations

from app.retrieval.utils import StageTimer, analyze_query, cache_key


class TestAnalyzeQuery:
    def test_blank_query_produces_empty_analysis(self) -> None:
        analysis = analyze_query("   ")
        assert analysis.normalized == ""
        assert analysis.identifier_tokens == []

    def test_extracts_identifier_like_tokens(self) -> None:
        analysis = analyze_query("Where is AuthService used to call getUserById?")
        assert "AuthService" in analysis.identifier_tokens
        assert "getUserById" in analysis.identifier_tokens

    def test_stopwords_and_short_words_are_excluded(self) -> None:
        analysis = analyze_query("Where is the code implemented for this?")
        assert analysis.identifier_tokens == []

    def test_deduplicates_case_insensitively(self) -> None:
        analysis = analyze_query("PaymentRepository paymentrepository PAYMENTREPOSITORY")
        assert len(analysis.identifier_tokens) == 1

    def test_respects_max_tokens(self) -> None:
        query = " ".join(f"identifier{i}" for i in range(20))
        analysis = analyze_query(query, max_tokens=3)
        assert len(analysis.identifier_tokens) == 3

    def test_normalized_collapses_whitespace(self) -> None:
        analysis = analyze_query("  multiple   spaces   here  ")
        assert analysis.normalized == "multiple spaces here"

    def test_raw_is_preserved_verbatim(self) -> None:
        analysis = analyze_query("  Where is X?  ")
        assert analysis.raw == "  Where is X?  "


class TestCacheKey:
    def test_same_inputs_produce_same_key(self) -> None:
        kwargs = dict(
            repository_id="repo-a", normalized_query="find auth", top_k=10,
            sources=("semantic", "lexical"), corpus_version="5:v1:2026-01-01",
        )
        assert cache_key(**kwargs) == cache_key(**kwargs)

    def test_different_repository_never_collides(self) -> None:
        base = dict(normalized_query="find auth", top_k=10, sources=("semantic",), corpus_version="v1")
        key_a = cache_key(repository_id="repo-a", **base)
        key_b = cache_key(repository_id="repo-b", **base)
        assert key_a != key_b
        assert "repo-a" in key_a and "repo-b" in key_b

    def test_source_order_does_not_affect_key(self) -> None:
        base = dict(repository_id="repo-a", normalized_query="q", top_k=10, corpus_version="v1")
        assert cache_key(sources=("semantic", "lexical"), **base) == cache_key(sources=("lexical", "semantic"), **base)

    def test_query_case_does_not_affect_key(self) -> None:
        base = dict(repository_id="repo-a", top_k=10, sources=("semantic",), corpus_version="v1")
        assert cache_key(normalized_query="Find Auth", **base) == cache_key(normalized_query="find auth", **base)

    def test_different_top_k_produces_different_key(self) -> None:
        base = dict(repository_id="repo-a", normalized_query="q", sources=("semantic",), corpus_version="v1")
        assert cache_key(top_k=5, **base) != cache_key(top_k=10, **base)

    def test_different_corpus_version_produces_different_key(self) -> None:
        """A re-index must invalidate old cached results — this is the mechanism that guarantees it."""
        base = dict(repository_id="repo-a", normalized_query="q", top_k=10, sources=("semantic",))
        assert cache_key(corpus_version="v1", **base) != cache_key(corpus_version="v2", **base)

    def test_reranking_flag_is_part_of_the_key(self) -> None:
        """An A/B rerank-override comparison must never read the other side's cached answer."""
        base = dict(repository_id="repo-a", normalized_query="q", top_k=10, sources=("semantic",), corpus_version="v1")
        assert cache_key(reranking_enabled=True, **base) != cache_key(reranking_enabled=False, **base)


class TestStageTimer:
    def test_records_stage_duration(self) -> None:
        timer = StageTimer()
        with timer.stage("work"):
            pass
        assert "work" in timer.as_dict()
        assert timer.as_dict()["work"] >= 0

    def test_record_accumulates_into_existing_stage(self) -> None:
        timer = StageTimer()
        timer.record("stage", 10)
        timer.record("stage", 5)
        assert timer.as_dict()["stage"] == 15

    def test_as_dict_returns_a_copy(self) -> None:
        timer = StageTimer()
        timer.record("a", 1)
        snapshot = timer.as_dict()
        snapshot["a"] = 999
        assert timer.as_dict()["a"] == 1
