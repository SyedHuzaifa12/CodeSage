"""Tests for the pieces of existing code that queue mode (ADR-028) changed:
the pipeline's stage hook / failure surfacing, and ``RepositoryService.clone_and_scan``.
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.db.postgres import check_postgres_connection, get_session_factory
from app.ingestion import parsing_service
from app.ingestion.exceptions import IndexingCancelledError
from app.models.repository import Repository
from app.repository import service as repo_service_module
from app.repository.exceptions import RepositoryCloneError, RepositoryTooLargeError
from app.repository.service import RepositoryService


@pytest_asyncio.fixture
async def stored_repo():
    if not await check_postgres_connection():
        pytest.skip("Postgres unreachable.")
    factory = get_session_factory()
    async with factory() as session:
        repository = Repository(
            name="p", github_url=f"https://github.com/o/{uuid.uuid4().hex[:8]}", local_path="/x",
            status="ready", indexing_status="indexing",
        )
        session.add(repository)
        await session.commit()
        repo_id = repository.id

    async def current() -> Repository:
        async with factory() as session:
            return (
                await session.execute(
                    select(Repository).where(Repository.id == repo_id).execution_options(populate_existing=True)
                )
            ).scalar_one()

    yield SimpleNamespace(id=repo_id, current=current)
    async with factory() as session:
        await session.execute(delete(Repository).where(Repository.id == repo_id))
        await session.commit()


@pytest.fixture
def stages(monkeypatch):
    """Replace the three pipeline stages with recorders; each test customises what they do."""
    state = SimpleNamespace(order=[], knowledge=SimpleNamespace(status="ready", error_message=None), parse_effect=None)

    async def parse(self, repository_id):
        state.order.append("parse")
        if state.parse_effect:
            await state.parse_effect(self._session, repository_id)

    async def analyze(self, repository_id):
        state.order.append("intelligence")

    async def knowledge(self, repository_id):
        state.order.append("knowledge")
        return state.knowledge

    monkeypatch.setattr(parsing_service.ParsingService, "parse_repository", parse)
    monkeypatch.setattr(parsing_service.RepositoryIntelligenceService, "analyze_repository", analyze)
    monkeypatch.setattr(parsing_service.KnowledgeService, "index_repository", knowledge)
    return state


class TestPipelineStageHook:
    async def test_a_successful_run_reports_no_failure_and_hooks_each_stage_in_order(self, stored_repo, stages):
        seen = []

        async def hook(stage):
            seen.append(stage)

        result = await parsing_service.run_parsing_pipeline(stored_repo.id, before_stage=hook)

        assert result is None
        assert seen == ["parse", "intelligence", "knowledge"] == stages.order

    async def test_runs_without_a_hook_exactly_as_before(self, stored_repo, stages):
        assert await parsing_service.run_parsing_pipeline(stored_repo.id) is None
        assert stages.order == ["parse", "intelligence", "knowledge"]

    async def test_cancelling_at_a_boundary_stops_the_run_and_rolls_back_its_uncommitted_work(self, stored_repo, stages):
        async def mark_indexed_uncommitted(session, repository_id):
            repository = await session.get(Repository, repository_id)
            repository.indexing_status = "indexed"  # never committed: the run is cancelled before the end
            await session.flush()

        stages.parse_effect = mark_indexed_uncommitted

        async def hook(stage):
            if stage == "intelligence":
                raise IndexingCancelledError("cancelled")

        with pytest.raises(IndexingCancelledError):
            await parsing_service.run_parsing_pipeline(stored_repo.id, before_stage=hook)

        assert stages.order == ["parse"]  # nothing after the boundary ran
        repository = await stored_repo.current()
        # Rolled back, and the pipeline did not stamp its own "crashed" failure over whatever the canceller set.
        assert (repository.indexing_status, repository.error_message) == ("indexing", None)

    async def test_a_failed_knowledge_stage_marks_the_repository_failed_and_is_reported(self, stored_repo, stages):
        stages.knowledge = SimpleNamespace(status="failed", error_message="The hosted embedding service is unavailable.")

        result = await parsing_service.run_parsing_pipeline(stored_repo.id)

        assert result == "The hosted embedding service is unavailable."
        repository = await stored_repo.current()
        assert (repository.indexing_status, repository.error_message) == (
            "failed", "The hosted embedding service is unavailable.",
        )

    async def test_a_failed_knowledge_stage_without_a_message_still_reports_something(self, stored_repo, stages):
        stages.knowledge = SimpleNamespace(status="failed", error_message=None)
        assert await parsing_service.run_parsing_pipeline(stored_repo.id) == "Knowledge indexing failed."

    async def test_an_unexpected_crash_still_marks_the_repository_failed_and_reraises(self, stored_repo, stages):
        async def explode(session, repository_id):
            raise RuntimeError("tree-sitter blew up")

        stages.parse_effect = explode

        with pytest.raises(RuntimeError, match="blew up"):
            await parsing_service.run_parsing_pipeline(stored_repo.id)

        repository = await stored_repo.current()
        assert repository.indexing_status == "failed" and "blew up" in repository.error_message


class _Session:
    def __init__(self):
        self.commits = 0

    async def commit(self):
        self.commits += 1


@pytest.fixture
def clone_env(monkeypatch, tmp_path):
    env = SimpleNamespace(
        threads=[], removed=[], order=[], measure=SimpleNamespace(exceeded=False), clone_error=None, scan_error=None,
    )

    def clone(url, path):
        env.threads.append(threading.current_thread())
        env.order.append("clone")
        if env.clone_error:
            raise env.clone_error

    def measure(path, max_files, max_bytes):
        env.threads.append(threading.current_thread())
        env.order.append(("measure", max_files, max_bytes))
        return env.measure

    def remove(path):
        env.removed.append(path)
        env.order.append("remove")

    monkeypatch.setattr(repo_service_module, "clone_repository", clone)
    monkeypatch.setattr(repo_service_module, "measure_tree", measure)
    monkeypatch.setattr(repo_service_module, "remove_local_clone", remove)
    monkeypatch.setattr(repo_service_module.repository_db, "save", AsyncMock())

    async def scan(repository_id):
        env.order.append("scan")
        if env.scan_error:
            raise env.scan_error
        return SimpleNamespace(excluded_files_count=3)

    env.session = _Session()
    env.service = RepositoryService(
        session=env.session, settings=SimpleNamespace(),
        workspace_service=SimpleNamespace(scan_repository=scan),
    )
    env.repo = SimpleNamespace(
        id=uuid.uuid4(), github_url="https://github.com/o/r", local_path=str(tmp_path / "clone"),
        status="cloning", indexing_status="not_started", indexing_progress=0, error_message=None,
    )
    return env


class TestCloneAndScan:
    async def test_clones_then_scans_and_marks_the_repository_ready(self, clone_env):
        await clone_env.service.clone_and_scan(clone_env.repo)

        assert clone_env.repo.status == "ready" and clone_env.repo.error_message is None
        assert clone_env.order == ["remove", "clone", "scan"]
        assert clone_env.repo.indexing_status == "not_started"  # the inline path leaves indexing to the caller

    async def test_a_stale_partial_clone_from_a_dead_attempt_is_removed_first(self, clone_env):
        await clone_env.service.clone_and_scan(clone_env.repo)
        assert clone_env.order[0] == "remove" and clone_env.removed[0] == Path(clone_env.repo.local_path)

    async def test_blocking_work_runs_off_the_event_loop_thread(self, clone_env):
        await clone_env.service.clone_and_scan(clone_env.repo, max_files=10, max_bytes=10)
        assert clone_env.threads and all(t is not threading.main_thread() for t in clone_env.threads)

    async def test_begin_indexing_flips_the_status_in_the_same_step_as_ready(self, clone_env):
        await clone_env.service.clone_and_scan(clone_env.repo, begin_indexing=True)
        assert (clone_env.repo.status, clone_env.repo.indexing_status) == ("ready", "indexing")

    async def test_progress_is_committed_when_asked_and_not_otherwise(self, clone_env):
        await clone_env.service.clone_and_scan(clone_env.repo)
        assert clone_env.session.commits == 0

        await clone_env.service.clone_and_scan(clone_env.repo, publish_progress=True)
        assert clone_env.session.commits == 2  # ready (visible before the scan), then the scan result

    async def test_guest_limits_are_enforced_and_an_oversized_clone_is_deleted(self, clone_env):
        clone_env.measure = SimpleNamespace(exceeded=True)

        with pytest.raises(RepositoryTooLargeError):
            await clone_env.service.clone_and_scan(clone_env.repo, max_files=1500, max_bytes=40_000_000, publish_progress=True)

        assert ("measure", 1500, 40_000_000) in clone_env.order
        assert clone_env.order.count("remove") == 2  # the pre-clean and the oversized clone
        assert clone_env.repo.status == "failed" and "larger than the free demo" in clone_env.repo.error_message
        assert clone_env.session.commits == 1  # the failure is visible to pollers immediately
        assert "scan" not in clone_env.order

    async def test_no_limits_means_no_measuring(self, clone_env):
        await clone_env.service.clone_and_scan(clone_env.repo)
        assert not any(isinstance(step, tuple) and step[0] == "measure" for step in clone_env.order)

    async def test_a_failed_clone_is_recorded_on_the_row_and_raised(self, clone_env):
        clone_env.clone_error = RepositoryCloneError("repository not found")

        with pytest.raises(RepositoryCloneError):
            await clone_env.service.clone_and_scan(clone_env.repo, publish_progress=True)

        assert clone_env.repo.status == "failed" and "not found" in clone_env.repo.error_message
        assert clone_env.session.commits == 1

    async def test_a_failed_first_scan_does_not_fail_the_clone(self, clone_env):
        clone_env.scan_error = RuntimeError("scan blew up")

        await clone_env.service.clone_and_scan(clone_env.repo)

        assert clone_env.repo.status == "ready"
