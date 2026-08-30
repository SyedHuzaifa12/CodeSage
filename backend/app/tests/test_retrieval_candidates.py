"""Unit tests for candidate deduplication and fusion/ranking (Sprint 4)."""
from __future__ import annotations

import uuid

from app.retrieval.candidates import Candidate, dedup_key_for, deduplicate, fuse_and_rank, query_has_test_intent

REPO = uuid.uuid4()
FILE_A = uuid.uuid4()
FILE_B = uuid.uuid4()
CHUNK_A = uuid.uuid4()
SYMBOL_A = uuid.uuid4()


def make_candidate(dedup_key: str, file_path: str, **source_scores: float) -> Candidate:
    return Candidate(
        dedup_key=dedup_key, repository_id=REPO, file_id=FILE_A, file_path=file_path,
        source_scores=dict(source_scores),
    )


class TestDedupKeyFor:
    def test_chunk_id_takes_priority(self) -> None:
        key = dedup_key_for(chunk_id=CHUNK_A, file_id=FILE_A, symbol_id=SYMBOL_A)
        assert key == f"chunk:{CHUNK_A}"

    def test_symbol_id_used_when_no_chunk(self) -> None:
        key = dedup_key_for(chunk_id=None, file_id=FILE_A, symbol_id=SYMBOL_A)
        assert key == f"symbol:{SYMBOL_A}"

    def test_file_id_is_the_fallback(self) -> None:
        key = dedup_key_for(chunk_id=None, file_id=FILE_A, symbol_id=None)
        assert key == f"file:{FILE_A}"


class TestDeduplicate:
    def test_distinct_keys_are_preserved(self) -> None:
        candidates = [make_candidate("a", "x.py", semantic=0.9), make_candidate("b", "y.py", lexical=0.8)]
        assert len(deduplicate(candidates)) == 2

    def test_same_key_merges_source_scores(self) -> None:
        candidates = [make_candidate("a", "x.py", semantic=0.7), make_candidate("a", "x.py", lexical=0.9)]
        merged = deduplicate(candidates)
        assert len(merged) == 1
        assert merged[0].source_scores == {"semantic": 0.7, "lexical": 0.9}

    def test_higher_score_wins_when_same_source_appears_twice(self) -> None:
        candidates = [make_candidate("a", "x.py", semantic=0.5), make_candidate("a", "x.py", semantic=0.9)]
        merged = deduplicate(candidates)
        assert merged[0].source_scores["semantic"] == 0.9

    def test_reasons_are_unioned_without_duplicates(self) -> None:
        first = make_candidate("a", "x.py", semantic=0.5)
        first.reasons = ["semantic hit"]
        second = make_candidate("a", "x.py", lexical=0.5)
        second.reasons = ["lexical hit", "semantic hit"]
        merged = deduplicate([first, second])
        assert merged[0].reasons == ["semantic hit", "lexical hit"]

    def test_merge_fills_in_missing_symbol_identity(self) -> None:
        bare = make_candidate("a", "x.py", semantic=0.5)
        with_symbol = Candidate(
            dedup_key="a", repository_id=REPO, file_id=FILE_A, file_path="x.py",
            symbol_id=SYMBOL_A, symbol_name="AuthService", source_scores={"lexical": 0.6},
        )
        merged = deduplicate([bare, with_symbol])
        assert merged[0].symbol_id == SYMBOL_A
        assert merged[0].symbol_name == "AuthService"

    def test_preserves_first_seen_order(self) -> None:
        candidates = [make_candidate("c", "c.py"), make_candidate("a", "a.py"), make_candidate("b", "b.py")]
        assert [c.dedup_key for c in deduplicate(candidates)] == ["c", "a", "b"]


class TestFuseAndRank:
    def _rank(self, candidates: list[Candidate], **overrides) -> list[Candidate]:
        params = dict(
            weight_semantic=0.5, weight_lexical=0.35, weight_structural=0.15,
            entry_point_boost=0.05, hotspot_boost=0.05,
            entry_point_paths=frozenset(), hotspot_module_paths=frozenset(), top_k=10,
        )
        params.update(overrides)
        return fuse_and_rank(candidates, **params)

    def test_higher_semantic_score_ranks_first(self) -> None:
        low = make_candidate("low", "low.py", semantic=0.2)
        high = make_candidate("high", "high.py", semantic=0.9)
        ranked = self._rank([low, high])
        assert ranked[0].dedup_key == "high"

    def test_weights_control_relative_contribution(self) -> None:
        semantic_only = make_candidate("s", "s.py", semantic=1.0)
        lexical_only = make_candidate("l", "l.py", lexical=1.0)
        ranked = self._rank([semantic_only, lexical_only], weight_semantic=0.9, weight_lexical=0.1)
        assert ranked[0].dedup_key == "s"

    def test_entry_point_boost_applied(self) -> None:
        candidate = make_candidate("e", "main.py", semantic=0.5)
        ranked = self._rank([candidate], entry_point_paths=frozenset({"main.py"}))
        assert ranked[0].final_score > 0.5 * 0.5
        assert any("entry point" in r for r in ranked[0].reasons)

    def test_hotspot_boost_applied(self) -> None:
        candidate = make_candidate("h", "app/core.py", semantic=0.5)
        ranked = self._rank([candidate], hotspot_module_paths=frozenset({"app.core"}))
        assert any("hotspot" in r for r in ranked[0].reasons)

    def test_top_k_truncates_results(self) -> None:
        candidates = [make_candidate(str(i), f"{i}.py", semantic=i / 10) for i in range(20)]
        ranked = self._rank(candidates, top_k=5)
        assert len(ranked) == 5

    def test_deterministic_tie_break_by_path_then_line(self) -> None:
        tie_a = Candidate(
            dedup_key="a", repository_id=REPO, file_id=FILE_A, file_path="b.py",
            start_line=10, source_scores={"semantic": 0.5},
        )
        tie_b = Candidate(
            dedup_key="b", repository_id=REPO, file_id=FILE_A, file_path="a.py",
            start_line=1, source_scores={"semantic": 0.5},
        )
        ranked_once = self._rank([tie_a, tie_b])
        ranked_again = self._rank([tie_b, tie_a])
        assert [c.dedup_key for c in ranked_once] == [c.dedup_key for c in ranked_again] == ["b", "a"]

    def test_score_is_missing_source_safe(self) -> None:
        """A candidate found by only one source must not error on the others' missing keys."""
        candidate = make_candidate("only-lexical", "x.py", lexical=0.5)
        ranked = self._rank([candidate])
        assert ranked[0].final_score == round(0.35 * 0.5, 6)

    def test_test_intent_boost_applied_to_test_files_only(self) -> None:
        test_file = make_candidate("t", "tests.py", semantic=0.5)
        impl_file = make_candidate("i", "app/auth.py", semantic=0.5)
        ranked = self._rank(
            [test_file, impl_file], test_intent_boost=0.2, query_test_intent=True
        )
        boosted = next(c for c in ranked if c.dedup_key == "t")
        unboosted = next(c for c in ranked if c.dedup_key == "i")
        assert boosted.final_score > unboosted.final_score
        assert any("test" in r for r in boosted.reasons)

    def test_test_intent_boost_not_applied_without_test_intent(self) -> None:
        test_file = make_candidate("t", "tests.py", semantic=0.5)
        ranked = self._rank([test_file], test_intent_boost=0.2, query_test_intent=False)
        assert ranked[0].final_score == round(0.5 * 0.5, 6)


class TestQueryHasTestIntent:
    def test_detects_test_word(self) -> None:
        assert query_has_test_intent("which tests cover authentication") is True

    def test_detects_testing_word(self) -> None:
        assert query_has_test_intent("is this covered by testing") is True

    def test_no_false_positive_on_unrelated_query(self) -> None:
        assert query_has_test_intent("where is authentication implemented") is False

    def test_case_insensitive(self) -> None:
        assert query_has_test_intent("Which TESTS relate to login") is True

    def test_punctuation_stripped(self) -> None:
        assert query_has_test_intent("any tests?") is True
