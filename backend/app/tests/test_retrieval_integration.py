"""Integration tests for the hybrid retrieval pipeline against real infrastructure.

Runs against the actual Postgres/Qdrant/Redis the app itself connects
to (via the same ``app.db.*`` helpers) — skipped cleanly (not failed)
when that infrastructure isn't reachable, e.g. a plain checkout without
``docker compose up``. Pure-logic unit tests for the same behaviors
live in ``test_retrieval_{utils,candidates,sources,cache}.py`` and
never need this guard.

Each test builds its own throwaway repository (and cleans it up via
cascade delete), so tests can run in any order without interfering
with each other or with real user data.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.db.postgres import check_postgres_connection, get_session_factory
from app.db.qdrant import check_qdrant_connection, get_qdrant_client
from app.db.redis import check_redis_connection, get_redis_client
from app.knowledge.qdrant_store import build_point, delete_points_by_repository, ensure_collection, upsert_points
from app.models.file import File
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.relationship import Relationship
from app.models.repository import Repository
from app.models.symbol import Symbol
from app.retrieval.service import RetrievalService


async def _infra_available() -> bool:
    return await check_postgres_connection() and await check_qdrant_connection() and await check_redis_connection()


@pytest_asyncio.fixture
async def infra():
    if not await _infra_available():
        pytest.skip("Postgres/Qdrant/Redis not reachable — skipping integration test.")
    yield


@pytest_asyncio.fixture
async def seeded_repository(infra):
    """Build one throwaway, fully-populated repository: files, symbols, relationships, a chunk + Qdrant point."""
    settings = get_settings()
    session_factory = get_session_factory()
    qdrant_client = get_qdrant_client()
    await ensure_collection(qdrant_client)

    async with session_factory() as session:
        repository = Repository(
            id=uuid.uuid4(), name=f"retrieval-test-{uuid.uuid4().hex[:8]}",
            local_path="/tmp/does-not-need-to-exist", status="ready", indexing_status="indexed",
        )
        session.add(repository)
        await session.flush()

        auth_file = File(id=uuid.uuid4(), repository_id=repository.id, path="app/auth.py", language="Python")
        payment_file = File(id=uuid.uuid4(), repository_id=repository.id, path="app/payment.py", language="Python")
        session.add_all([auth_file, payment_file])
        await session.flush()

        auth_service = Symbol(
            id=uuid.uuid4(), file_id=auth_file.id, name="AuthService", qualified_name="app.auth.AuthService",
            symbol_type="class", visibility="public", start_line=1, end_line=30,
        )
        get_user = Symbol(
            id=uuid.uuid4(), file_id=auth_file.id, name="getUserById", qualified_name="app.auth.getUserById",
            symbol_type="function", visibility="public", start_line=32, end_line=40,
        )
        payment_repo = Symbol(
            id=uuid.uuid4(), file_id=payment_file.id, name="PaymentRepository",
            qualified_name="app.payment.PaymentRepository", symbol_type="class",
            visibility="public", start_line=1, end_line=15,
        )
        session.add_all([auth_service, get_user, payment_repo])
        await session.flush()

        session.add(
            Relationship(
                repository_id=repository.id, source_symbol="app.auth.AuthService",
                target_symbol="app.payment.PaymentRepository", relationship_type="calls",
            )
        )

        chunk_id = uuid.uuid4()
        session.add(
            KnowledgeChunk(
                id=chunk_id, repository_id=repository.id, file_id=auth_file.id, symbol_id=auth_service.id,
                chunk_index=0, chunk_type="symbol", start_line=1, end_line=30, char_count=400,
                language="Python", content_hash="a" * 64, file_content_hash="b" * 64,
                embedding_model_version=settings.llm.embedding_version,
            )
        )
        await session.commit()

    from app.knowledge.embedding import get_embedding_provider

    provider = get_embedding_provider()
    vector = provider.embed(["class AuthService: handles user authentication and login"])[0]
    point = build_point(
        chunk_id, vector, repository_id=repository.id, file_id=auth_file.id, symbol_id=auth_service.id,
        file_path="app/auth.py", language="Python", chunk_type="symbol", start_line=1, end_line=30,
        content_hash="a" * 64, embedding_model_version=settings.llm.embedding_version,
    )
    await upsert_points(qdrant_client, [point])

    yield repository.id, {
        "auth_service_id": auth_service.id, "get_user_id": get_user.id, "payment_repo_id": payment_repo.id,
    }

    await delete_points_by_repository(qdrant_client, repository.id)
    async with session_factory() as session:
        db_repository = await session.get(Repository, repository.id)
        if db_repository is not None:
            await session.delete(db_repository)
            await session.commit()


class TestPostgresLexicalRetrieval:
    async def test_exact_identifier_match(self, seeded_repository) -> None:
        repository_id, _ = seeded_repository
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            result = await service.query(repository_id, "AuthService", top_k=10, sources=["lexical"])
        assert any(r.symbol_name == "AuthService" for r in result.results)

    async def test_camel_case_identifier_match(self, seeded_repository) -> None:
        repository_id, _ = seeded_repository
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            result = await service.query(repository_id, "getUserById", top_k=10, sources=["lexical"])
        assert any(r.symbol_name == "getUserById" for r in result.results)

    async def test_no_match_returns_empty_results_not_an_error(self, seeded_repository) -> None:
        repository_id, _ = seeded_repository
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            result = await service.query(repository_id, "CompletelyUnrelatedXyzToken", top_k=10, sources=["lexical"])
        assert result.results == []


class TestQdrantSemanticRetrieval:
    async def test_semantic_query_finds_the_embedded_chunk(self, seeded_repository) -> None:
        repository_id, _ = seeded_repository
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            result = await service.query(
                repository_id, "how does user login and authentication work", top_k=10, sources=["semantic"]
            )
        assert len(result.results) >= 1
        assert result.results[0].file_path == "app/auth.py"


class TestStructuralRetrieval:
    async def test_structural_expands_from_a_lexical_seed(self, seeded_repository) -> None:
        repository_id, _ = seeded_repository
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            result = await service.query(repository_id, "AuthService", top_k=10, sources=["lexical", "structural"])
        symbol_names = {r.symbol_name for r in result.results}
        assert "AuthService" in symbol_names
        assert "PaymentRepository" in symbol_names  # reached via the "calls" relationship, one hop


class TestHybridPipeline:
    async def test_hybrid_query_combines_and_ranks_all_sources(self, seeded_repository) -> None:
        repository_id, _ = seeded_repository
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            result = await service.query(repository_id, "AuthService authentication", top_k=10, sources=None)
        assert len(result.results) >= 1
        assert result.stats.candidates_after_dedup <= (
            result.stats.candidates_semantic + result.stats.candidates_lexical + result.stats.candidates_structural
        )
        ranks = [r.rank for r in result.results]
        assert ranks == sorted(ranks)

    async def test_empty_query_short_circuits_cleanly(self, seeded_repository) -> None:
        repository_id, _ = seeded_repository
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            result = await service.query(repository_id, "   ", top_k=10, sources=None)
        assert result.results == []
        assert result.stats.sources_failed == []


class TestRedisCaching:
    async def test_repeated_query_is_served_from_cache(self, seeded_repository) -> None:
        repository_id, _ = seeded_repository
        session_factory = get_session_factory()

        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            first = await service.query(repository_id, "AuthService", top_k=10, sources=["lexical"])
        assert first.stats.cache_hit is False

        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            second = await service.query(repository_id, "AuthService", top_k=10, sources=["lexical"])
        assert second.stats.cache_hit is True
        assert [r.symbol_name for r in second.results] == [r.symbol_name for r in first.results]

    async def test_redis_unavailable_falls_back_to_live_computation(
        self, seeded_repository, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repository_id, _ = seeded_repository

        class _BrokenRedis:
            async def get(self, *args, **kwargs):
                raise ConnectionError("simulated outage")

            async def set(self, *args, **kwargs):
                raise ConnectionError("simulated outage")

        import app.retrieval.service as service_module

        monkeypatch.setattr(service_module, "get_redis_client", lambda: _BrokenRedis())

        session_factory = get_session_factory()
        async with session_factory() as session:
            service = RetrievalService(session, get_settings())
            result = await service.query(repository_id, "AuthService", top_k=10, sources=["lexical"])
        assert any(r.symbol_name == "AuthService" for r in result.results)


class TestRepositoryIsolation:
    async def test_repository_a_results_never_appear_for_repository_b(self, seeded_repository) -> None:
        repository_a_id, _ = seeded_repository
        settings = get_settings()
        session_factory = get_session_factory()

        async with session_factory() as session:
            repository_b = Repository(
                id=uuid.uuid4(), name=f"retrieval-test-b-{uuid.uuid4().hex[:8]}",
                local_path="/tmp/does-not-need-to-exist", status="ready", indexing_status="indexed",
            )
            session.add(repository_b)
            await session.commit()

        try:
            async with session_factory() as session:
                service = RetrievalService(session, settings)
                result_a = await service.query(repository_a_id, "AuthService", top_k=10, sources=["lexical"])
                result_b = await service.query(repository_b.id, "AuthService", top_k=10, sources=["lexical"])

            assert len(result_a.results) >= 1
            assert result_b.results == []
            assert all(r.repository_id == repository_a_id for r in result_a.results)
        finally:
            async with session_factory() as session:
                db_repository_b = await session.get(Repository, repository_b.id)
                if db_repository_b is not None:
                    await session.delete(db_repository_b)
                    await session.commit()


class TestConcurrentRetrieval:
    """Pre-Sprint-5 hardening: concurrent requests must not corrupt or cross-contaminate results.

    Each concurrent query uses its own session (as a real request would
    via FastAPI's per-request ``Depends(get_db)``) — this exercises the
    *process-wide singletons* (embedding provider, Qdrant/Redis
    clients) under real concurrency, which per-request session
    isolation alone wouldn't catch.
    """

    async def test_concurrent_queries_do_not_interfere(self, seeded_repository) -> None:
        repository_id, _ = seeded_repository
        session_factory = get_session_factory()
        settings = get_settings()

        async def run_one(query_text: str):
            async with session_factory() as session:
                service = RetrievalService(session, settings)
                return await service.query(repository_id, query_text, top_k=5, sources=["lexical"])

        results = await asyncio.gather(
            run_one("AuthService"), run_one("getUserById"), run_one("PaymentRepository"),
            run_one("AuthService"), run_one("getUserById"),
        )

        assert all(r.repository_id == repository_id for result in results for r in result.results)
        assert any(r.symbol_name == "AuthService" for r in results[0].results)
        assert any(r.symbol_name == "getUserById" for r in results[1].results)
        assert any(r.symbol_name == "PaymentRepository" for r in results[2].results)
        # The two repeated queries must be internally consistent with each other.
        assert [r.symbol_name for r in results[0].results] == [r.symbol_name for r in results[3].results]
