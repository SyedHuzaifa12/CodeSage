"""Integration tests for the AI Engine against real infrastructure, fake LLM only.

Mirrors ``test_retrieval_integration.py``'s pattern exactly (same
skip-guard, same throwaway-repository-per-test approach) — validates
real Postgres/Qdrant/Redis wiring end-to-end through the actual
``AIOrchestratorService``, without any real (paid, flaky) LLM call.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio

from app.ai.exceptions import RepositoryNotReadyForAIError
from app.ai.llm.provider import LLMCompletion
from app.ai.services.ai_service import AIOrchestratorService
from app.core.config import get_settings
from app.db.postgres import check_postgres_connection, get_session_factory
from app.db.qdrant import check_qdrant_connection, get_qdrant_client
from app.db.redis import check_redis_connection
from app.knowledge.qdrant_store import build_point, delete_points_by_repository, ensure_collection, upsert_points
from app.models.file import File
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_index_state import KnowledgeIndexState
from app.models.repository import Repository
from app.models.symbol import Symbol
from app.repository.exceptions import RepositoryNotFoundError


async def _infra_available() -> bool:
    return await check_postgres_connection() and await check_qdrant_connection() and await check_redis_connection()


@pytest_asyncio.fixture
async def infra():
    if not await _infra_available():
        pytest.skip("Postgres/Qdrant/Redis not reachable — skipping integration test.")
    yield


@pytest.fixture(autouse=True)
def _fake_llm_provider(monkeypatch: pytest.MonkeyPatch):
    """Every integration test uses a deterministic fake LLM — never a real paid API call."""

    class FakeProvider:
        provider_name = "fake"
        model = "fake-model"

        async def complete(self, system_prompt: str, user_prompt: str) -> LLMCompletion:
            return LLMCompletion(
                text="AuthService in app/auth.py handles authentication.",
                provider=self.provider_name, model=self.model,
            )

    import app.ai.engine.reasoning as reasoning_module

    monkeypatch.setattr(reasoning_module, "get_llm_provider", lambda: FakeProvider())
    yield


@pytest_asyncio.fixture
async def seeded_ai_repository(infra):
    """A throwaway, fully-indexed repository: files, symbols, a knowledge chunk + Qdrant point, ready for AI queries."""
    settings = get_settings()
    session_factory = get_session_factory()
    qdrant_client = get_qdrant_client()
    await ensure_collection(qdrant_client)

    async with session_factory() as session:
        repository = Repository(
            id=uuid.uuid4(), name=f"ai-test-{uuid.uuid4().hex[:8]}", local_path="/tmp/does-not-need-to-exist",
            status="ready", indexing_status="indexed",
        )
        session.add(repository)
        await session.flush()

        auth_file = File(id=uuid.uuid4(), repository_id=repository.id, path="app/auth.py", language="Python")
        session.add(auth_file)
        await session.flush()

        auth_service = Symbol(
            id=uuid.uuid4(), file_id=auth_file.id, name="AuthService", qualified_name="app.auth.AuthService",
            symbol_type="class", visibility="public", start_line=1, end_line=30,
        )
        session.add(auth_service)
        await session.flush()

        chunk_id = uuid.uuid4()
        session.add(
            KnowledgeChunk(
                id=chunk_id, repository_id=repository.id, file_id=auth_file.id, symbol_id=auth_service.id,
                chunk_index=0, chunk_type="symbol", start_line=1, end_line=30, char_count=400,
                language="Python", content_hash="a" * 64, file_content_hash="b" * 64,
                embedding_model_version=settings.llm.embedding_version,
            )
        )
        session.add(
            KnowledgeIndexState(
                id=uuid.uuid4(), repository_id=repository.id, status="ready", progress=100,
                total_chunks=1, embedding_model_version=settings.llm.embedding_version,
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

    yield repository.id

    await delete_points_by_repository(qdrant_client, repository.id)
    async with session_factory() as session:
        db_repository = await session.get(Repository, repository.id)
        if db_repository is not None:
            await session.delete(db_repository)
            await session.commit()


class TestAIServiceHappyPath:
    async def test_ask_returns_grounded_answer(self, seeded_ai_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = AIOrchestratorService(session, get_settings())
            response = await service.ask(seeded_ai_repository, "how is authentication implemented?")

        assert "AuthService" in response.answer
        assert response.verification.status in ("supported", "partially_supported")
        assert response.metadata.provider == "fake"

    async def test_unknown_repository_raises(self) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            if not await _infra_available():
                pytest.skip("Postgres/Qdrant/Redis not reachable.")
            service = AIOrchestratorService(session, get_settings())
            with pytest.raises(RepositoryNotFoundError):
                await service.ask(uuid.uuid4(), "anything")


class TestAIServiceCache:
    async def test_repeated_query_is_served_from_cache(self, seeded_ai_repository) -> None:
        session_factory = get_session_factory()

        async with session_factory() as session:
            service = AIOrchestratorService(session, get_settings())
            first = await service.ask(seeded_ai_repository, "how is authentication implemented?")
        assert first.metadata.cache_hit is False

        async with session_factory() as session:
            service = AIOrchestratorService(session, get_settings())
            second = await service.ask(seeded_ai_repository, "how is authentication implemented?")
        assert second.metadata.cache_hit is True
        assert second.answer == first.answer

    async def test_force_refresh_still_populates_cache_for_later_normal_calls(self, seeded_ai_repository) -> None:
        """Regression: force_refresh must skip the cache *read*, not skip populating the cache entirely."""
        session_factory = get_session_factory()

        async with session_factory() as session:
            service = AIOrchestratorService(session, get_settings())
            forced = await service.ask(seeded_ai_repository, "how is authentication implemented?", force_refresh=True)
        assert forced.metadata.cache_hit is False

        async with session_factory() as session:
            service = AIOrchestratorService(session, get_settings())
            normal = await service.ask(seeded_ai_repository, "how is authentication implemented?")
        assert normal.metadata.cache_hit is True

    async def test_force_refresh_bypasses_cache(self, seeded_ai_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = AIOrchestratorService(session, get_settings())
            await service.ask(seeded_ai_repository, "how is authentication implemented?")

        async with session_factory() as session:
            service = AIOrchestratorService(session, get_settings())
            refreshed = await service.ask(seeded_ai_repository, "how is authentication implemented?", force_refresh=True)
        assert refreshed.metadata.cache_hit is False


class TestAIServiceIsolation:
    async def test_repository_a_answer_never_served_for_repository_b(self, seeded_ai_repository) -> None:
        repository_a_id = seeded_ai_repository
        settings = get_settings()
        session_factory = get_session_factory()

        async with session_factory() as session:
            repository_b = Repository(
                id=uuid.uuid4(), name=f"ai-test-b-{uuid.uuid4().hex[:8]}", local_path="/tmp/x",
                status="ready", indexing_status="indexed",
            )
            session.add(repository_b)
            await session.flush()
            session.add(KnowledgeIndexState(id=uuid.uuid4(), repository_id=repository_b.id, status="ready", progress=100))
            await session.commit()

        try:
            async with session_factory() as session:
                service = AIOrchestratorService(session, settings)
                response_a = await service.ask(repository_a_id, "how is authentication implemented?")
                response_b = await service.ask(repository_b.id, "how is authentication implemented?")

            assert response_a.repository_id == repository_a_id
            assert response_b.repository_id == repository_b.id
            assert response_b.evidence == []  # repository B has no indexed chunks at all
        finally:
            async with session_factory() as session:
                db_repository_b = await session.get(Repository, repository_b.id)
                if db_repository_b is not None:
                    await session.delete(db_repository_b)
                    await session.commit()


class TestAIServiceValidation:
    async def test_unindexed_repository_raises(self) -> None:
        if not await _infra_available():
            pytest.skip("Postgres/Qdrant/Redis not reachable.")
        session_factory = get_session_factory()
        async with session_factory() as session:
            repository = Repository(
                id=uuid.uuid4(), name=f"ai-test-unindexed-{uuid.uuid4().hex[:8]}", local_path="/tmp/x", status="ready",
            )
            session.add(repository)
            await session.commit()
        try:
            async with session_factory() as session:
                service = AIOrchestratorService(session, get_settings())
                with pytest.raises(RepositoryNotReadyForAIError):
                    await service.ask(repository.id, "anything")
        finally:
            async with session_factory() as session:
                db_repository = await session.get(Repository, repository.id)
                if db_repository is not None:
                    await session.delete(db_repository)
                    await session.commit()


class TestAIServiceConcurrency:
    async def test_concurrent_asks_do_not_interfere(self, seeded_ai_repository) -> None:
        session_factory = get_session_factory()
        settings = get_settings()

        async def run_one(query: str):
            async with session_factory() as session:
                service = AIOrchestratorService(session, settings)
                return await service.ask(seeded_ai_repository, query, force_refresh=True)

        responses = await asyncio.gather(
            run_one("how is authentication implemented?"), run_one("what does AuthService do?"),
            run_one("how is authentication implemented?"),
        )
        assert all(r.repository_id == seeded_ai_repository for r in responses)
