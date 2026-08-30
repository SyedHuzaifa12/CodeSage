"""Unit tests for the retrieval-result cache and evidence-response round-tripping (Sprint 4)."""
from __future__ import annotations

import uuid

from app.retrieval.cache import get_cached_result, set_cached_result
from app.retrieval.schemas import EvidenceResult, RetrievalQueryData, RetrievalStats, SourceScore

REPO = uuid.uuid4()
FILE = uuid.uuid4()


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value


class _BrokenRedis:
    async def get(self, key: str):
        raise ConnectionError("simulated redis outage")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        raise ConnectionError("simulated redis outage")


def make_response(query: str = "auth") -> RetrievalQueryData:
    return RetrievalQueryData(
        repository_id=REPO, query=query, top_k=10, sources_requested=["semantic", "lexical"],
        results=[
            EvidenceResult(
                rank=1, final_score=0.82, repository_id=REPO, file_id=FILE, file_path="app/auth.py",
                chunk_id=None, symbol_id=None, symbol_name="AuthService", qualified_name="app.auth.AuthService",
                symbol_type="class", start_line=1, end_line=20, language="Python",
                sources=["lexical", "semantic"],
                source_scores=[SourceScore(source="lexical", score=1.0), SourceScore(source="semantic", score=0.7)],
                reasons=["symbol name matches 'AuthService'"],
            )
        ],
        stats=RetrievalStats(
            candidates_semantic=3, candidates_lexical=2, candidates_structural=0, candidates_after_dedup=4,
            stage_latency_ms={"retrieval_parallel": 40, "fusion": 1}, total_latency_ms=41,
            cache_hit=False, sources_failed=[],
        ),
    )


class TestEvidenceRoundTrip:
    def test_response_round_trips_through_json(self) -> None:
        original = make_response()
        restored = RetrievalQueryData.model_validate_json(original.model_dump_json())
        assert restored == original

    def test_empty_results_round_trip(self) -> None:
        original = make_response()
        original.results = []
        restored = RetrievalQueryData.model_validate_json(original.model_dump_json())
        assert restored.results == []


class TestRetrievalCache:
    async def test_miss_on_empty_cache(self) -> None:
        assert await get_cached_result(_FakeRedis(), "some-key") is None

    async def test_write_then_read_round_trips(self) -> None:
        client = _FakeRedis()
        original = make_response()
        await set_cached_result(client, "key-a", original, ttl_seconds=300)
        restored = await get_cached_result(client, "key-a")
        assert restored == original

    async def test_corrupt_entry_is_treated_as_a_miss(self) -> None:
        client = _FakeRedis()
        client._store["key-a"] = "not valid json"
        assert await get_cached_result(client, "key-a") is None

    async def test_redis_outage_on_read_is_a_miss_not_an_error(self) -> None:
        assert await get_cached_result(_BrokenRedis(), "key-a") is None

    async def test_redis_outage_on_write_does_not_raise(self) -> None:
        await set_cached_result(_BrokenRedis(), "key-a", make_response(), ttl_seconds=300)
