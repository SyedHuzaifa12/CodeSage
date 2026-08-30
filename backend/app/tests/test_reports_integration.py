"""Integration tests for the Reports module against real infrastructure, fake LLM only.

Mirrors ``test_ai_integration.py``'s pattern exactly (same skip-guard,
same throwaway-repository-per-test approach): validates real
Postgres/Redis wiring end-to-end through the actual ``ReportService``,
without any real (paid, flaky) LLM call. Qdrant/embeddings are not
needed here — report generation reuses Sprint 2A/2B's relational data,
never vector search.
"""
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.ai.llm.provider import LLMCompletion
from app.core.config import get_settings
from app.db.postgres import check_postgres_connection, get_session_factory
from app.db.qdrant import check_qdrant_connection
from app.db.redis import check_redis_connection, get_redis_client
from app.models.file import File
from app.models.knowledge_index_state import KnowledgeIndexState
from app.models.relationship import Relationship
from app.models.repository import Repository
from app.models.repository_intelligence import RepositoryIntelligence
from app.models.symbol import Symbol
from app.reports.exceptions import ReportRepositoryNotIndexedError
from app.reports.service import ReportService
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

    async def fake_complete_with_retry(provider, system_prompt, user_prompt, settings):
        return LLMCompletion(
            text='{"summary": "A demo repository.", "sections": {'
            '"Narrative Overview": "See app/main.py for the entry point.", '
            '"Architecture Narrative": "The app module is central.", '
            '"Getting Started Narrative": "Start at app/main.py."}}',
            provider="fake", model="fake-model",
        )

    import app.reports.synthesis as synthesis_module

    monkeypatch.setattr(synthesis_module, "get_llm_provider", lambda: type("P", (), {"provider_name": "fake", "model": "fake-model"})())
    monkeypatch.setattr(synthesis_module, "complete_with_retry", fake_complete_with_retry)
    yield


async def _build_seeded_repository(name_prefix: str) -> uuid.UUID:
    session_factory = get_session_factory()
    settings = get_settings()
    async with session_factory() as session:
        repository = Repository(
            id=uuid.uuid4(), name=f"{name_prefix}-{uuid.uuid4().hex[:8]}", local_path="/tmp/does-not-need-to-exist",
            status="ready", indexing_status="indexed",
        )
        session.add(repository)
        await session.flush()

        main_file = File(id=uuid.uuid4(), repository_id=repository.id, path="app/main.py", language="Python")
        auth_file = File(id=uuid.uuid4(), repository_id=repository.id, path="app/auth.py", language="Python")
        session.add_all([main_file, auth_file])
        await session.flush()

        auth_service = Symbol(
            id=uuid.uuid4(), file_id=auth_file.id, name="AuthService", qualified_name="app.auth.AuthService",
            symbol_type="class", visibility="public", start_line=1, end_line=30,
        )
        session.add(auth_service)

        session.add(
            Relationship(
                id=uuid.uuid4(), repository_id=repository.id, source_symbol="app.main",
                target_symbol="app.auth", relationship_type="depends_on",
            )
        )
        session.add(
            RepositoryIntelligence(
                id=uuid.uuid4(), repository_id=repository.id, status="ready", languages={"Python": 2},
                entry_points=["app/main.py"], largest_modules=[{"path": "app/auth.py", "symbol_count": 1}],
                dependency_hotspots=[{"module_path": "app.auth", "incoming_dependencies": 1}],
                architecture_hints=[], circular_dependencies=[], orphan_files=[],
            )
        )
        session.add(
            KnowledgeIndexState(
                id=uuid.uuid4(), repository_id=repository.id, status="ready", progress=100,
                total_chunks=2, embedding_model_version=settings.llm.embedding_version,
            )
        )
        await session.commit()
        return repository.id


async def _delete_repository(repository_id: uuid.UUID) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        repository = await session.get(Repository, repository_id)
        if repository is not None:
            await session.delete(repository)
            await session.commit()


@pytest_asyncio.fixture
async def seeded_report_repository(infra):
    repository_id = await _build_seeded_repository("reports-test")
    yield repository_id
    await _delete_repository(repository_id)


class TestReportGenerationHappyPath:
    async def test_generate_overview_report(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            response = await service.generate_or_get(seeded_report_repository, "summary")

        assert response.status == "ready"
        assert response.repository_id == seeded_report_repository
        assert response.sections
        assert response.stale is False

    async def test_generate_architecture_report_has_diagram(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            response = await service.generate_or_get(seeded_report_repository, "architecture")

        assert response.diagrams
        assert response.diagrams[0].mermaid_code.startswith("flowchart TD")

    async def test_generate_dependency_risk_report(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            response = await service.generate_or_get(seeded_report_repository, "dependency_risk")

        assert response.status == "ready"
        assert any(s.heading == "Dependency Hotspots" for s in response.sections)

    async def test_unindexed_repository_raises(self) -> None:
        if not await _infra_available():
            pytest.skip("Postgres/Qdrant/Redis not reachable.")
        session_factory = get_session_factory()
        async with session_factory() as session:
            repository = Repository(
                id=uuid.uuid4(), name=f"reports-unindexed-{uuid.uuid4().hex[:8]}", local_path="/tmp/x", status="ready",
            )
            session.add(repository)
            await session.commit()
        try:
            async with session_factory() as session:
                service = ReportService(session, get_settings())
                with pytest.raises(ReportRepositoryNotIndexedError):
                    await service.generate_or_get(repository.id, "summary")
        finally:
            await _delete_repository(repository.id)

    async def test_unknown_repository_raises(self) -> None:
        if not await _infra_available():
            pytest.skip("Postgres/Qdrant/Redis not reachable.")
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            with pytest.raises(RepositoryNotFoundError):
                await service.generate_or_get(uuid.uuid4(), "summary")


class TestReportCache:
    async def test_second_call_is_served_from_cache(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            first = await service.generate_or_get(seeded_report_repository, "health")
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            second = await service.generate_or_get(seeded_report_repository, "health")

        assert first.id == second.id  # served from cache/latest-ready, not a new append-only row

    async def test_force_regenerate_creates_a_new_row(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            first = await service.generate_or_get(seeded_report_repository, "onboarding")
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            second = await service.generate_or_get(seeded_report_repository, "onboarding", force_regenerate=True)

        assert first.id != second.id  # append-only: a new row, never an in-place overwrite


class TestReportPersistenceAndListing:
    async def test_get_latest_after_generation(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            generated = await service.generate_or_get(seeded_report_repository, "summary")
            await session.commit()  # ReportService never commits itself (that's get_db's job in production)
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            fetched = await service.get_latest(seeded_report_repository, "summary")

        assert fetched is not None
        assert fetched.id == generated.id

    async def test_get_latest_returns_none_when_never_generated(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            fetched = await service.get_latest(seeded_report_repository, "health")
        assert fetched is None

    async def test_list_reports_latest_only_dedupes_by_type(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            await service.generate_or_get(seeded_report_repository, "summary")
            await service.generate_or_get(seeded_report_repository, "summary", force_regenerate=True)
            await service.generate_or_get(seeded_report_repository, "architecture")
            await session.commit()

        async with session_factory() as session:
            service = ReportService(session, get_settings())
            latest = await service.list_reports(seeded_report_repository, latest_only=True)
            full_history = await service.list_reports(seeded_report_repository, latest_only=False)

        assert len({r.report_type for r in latest}) == len(latest)
        assert len(full_history) >= 3


class TestReportIsolation:
    async def test_reports_are_never_shared_across_repositories(self, seeded_report_repository) -> None:
        repository_b_id = await _build_seeded_repository("reports-test-b")
        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                service = ReportService(session, get_settings())
                response_a = await service.generate_or_get(seeded_report_repository, "summary")
                response_b = await service.generate_or_get(repository_b_id, "summary")

            assert response_a.repository_id == seeded_report_repository
            assert response_b.repository_id == repository_b_id
            assert response_a.id != response_b.id
        finally:
            await _delete_repository(repository_b_id)


class TestIndexVersionInvalidation:
    async def test_reindex_changes_repository_version_and_triggers_regeneration(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            first = await service.generate_or_get(seeded_report_repository, "health")

        # Simulate a re-index bumping the knowledge index state's version fingerprint.
        async with session_factory() as session:
            from app.knowledge import repository as knowledge_db

            state = await knowledge_db.get_index_state(session, seeded_report_repository)
            state.total_chunks += 1
            await session.commit()

        async with session_factory() as session:
            service = ReportService(session, get_settings())
            second = await service.generate_or_get(seeded_report_repository, "health")

        assert second.id != first.id
        assert second.repository_version != first.repository_version

    async def test_stale_flag_set_when_repository_reindexed_after_generation(self, seeded_report_repository) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = ReportService(session, get_settings())
            await service.generate_or_get(seeded_report_repository, "onboarding")
            await session.commit()

        async with session_factory() as session:
            from app.knowledge import repository as knowledge_db

            state = await knowledge_db.get_index_state(session, seeded_report_repository)
            state.total_chunks += 1
            await session.commit()

        async with session_factory() as session:
            service = ReportService(session, get_settings())
            fetched = await service.get_latest(seeded_report_repository, "onboarding")

        assert fetched is not None
        assert fetched.stale is True


@pytest_asyncio.fixture(autouse=True)
async def _clear_report_redis_keys():
    """Prevent cross-test cache bleed within this file's Redis instance."""
    yield
    try:
        client = get_redis_client()
        async for key in client.scan_iter(match="codesage:reports:*"):
            await client.delete(key)
    except Exception:
        pass
