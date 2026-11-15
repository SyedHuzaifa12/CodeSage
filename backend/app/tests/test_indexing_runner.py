"""Tests for the indexing runner (ADR-028): claiming, retries, cancellation, leases, wake-driven loop.

Real Postgres (the job states are the point), fake pipelines (the pipelines have their own tests).
Skipped when Postgres is unreachable or ``indexing_jobs`` is not migrated.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Optional

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text

from app.core.config import get_settings
from app.db.postgres import check_postgres_connection, get_session_factory
from app.indexing import repository as jobs
from app.indexing import runner as runner_module
from app.indexing.runner import IndexingRunner
from app.models.indexing_job import IndexingJob
from app.models.knowledge_index_state import KnowledgeIndexState
from app.models.repository import Repository
from app.repository.exceptions import RepositoryCloneError
from app.repository.service import RepositoryService

CANCEL_MESSAGE = "Indexing was cancelled by request."


@pytest_asyncio.fixture
async def world(monkeypatch):
    if not await check_postgres_connection():
        pytest.skip("Postgres unreachable.")
    factory = get_session_factory()
    try:
        async with factory() as session:
            busy = (
                await session.execute(
                    select(func.count()).select_from(IndexingJob).where(IndexingJob.status.in_(("queued", "running")))
                )
            ).scalar_one()
    except Exception:  # noqa: BLE001
        pytest.skip("`alembic upgrade head` not applied (indexing_jobs missing).")
    if busy:
        pytest.skip("Other active indexing jobs exist in this database; these tests would race with them.")

    settings = get_settings()
    monkeypatch.setattr(settings.indexing, "indexing_heartbeat_seconds", 0.05)
    monkeypatch.setattr(settings.indexing, "indexing_lease_seconds", 60)
    monkeypatch.setattr(settings.indexing, "indexing_retry_backoff_seconds", 0)
    created: list[uuid.UUID] = []
    runners: list[IndexingRunner] = []

    class World:
        factory = staticmethod(get_session_factory())
        calls: list[tuple] = []
        pipeline_result: Optional[str] = None
        real_scan_check = False  # fake repositories have no clone on disk; one test turns the real check on

        async def repo(self, status="ready", indexing_status="indexing") -> uuid.UUID:
            async with factory() as session:
                repository = Repository(
                    name="r", github_url=f"https://github.com/o/{uuid.uuid4().hex[:8]}",
                    local_path="/tmp/does-not-matter", status=status, indexing_status=indexing_status,
                )
                session.add(repository)
                await session.commit()
                created.append(repository.id)
                return repository.id

        async def job(self, repository_id, kind="full_index", max_attempts=3, **kw) -> uuid.UUID:
            async with factory() as session:
                row = await jobs.enqueue(session, repository_id, kind, max_attempts=max_attempts, **kw)
                await session.commit()
                return row.id

        async def get_job(self, job_id) -> IndexingJob:
            async with factory() as session:
                return await jobs.get_job(session, job_id)

        async def get_repo(self, repository_id) -> Repository:
            async with factory() as session:
                return (
                    await session.execute(
                        select(Repository).where(Repository.id == repository_id).execution_options(populate_existing=True)
                    )
                ).scalar_one()

        async def sql(self, statement: str, **params):
            async with factory() as session:
                await session.execute(text(statement), params)
                await session.commit()

        def runner(self, name="test-worker") -> IndexingRunner:
            r = IndexingRunner(settings, worker_id=name)
            runners.append(r)
            return r

        async def wait_for(self, job_id, status: str, timeout=6.0) -> IndexingJob:
            deadline = asyncio.get_event_loop().time() + timeout
            while True:
                job = await self.get_job(job_id)
                if job is not None and job.status == status:
                    return job
                if asyncio.get_event_loop().time() > deadline:
                    raise AssertionError(f"job stayed {job.status if job else None!r}, wanted {status!r}")
                await asyncio.sleep(0.05)

    w = World()
    w.calls = []

    async def fake_pipeline(repository_id, before_stage=None):
        w.calls.append(("pipeline", repository_id))
        if before_stage:
            for stage in ("parse", "intelligence", "knowledge"):
                await before_stage(stage)
        if isinstance(w.pipeline_result, Exception):
            raise w.pipeline_result
        return w.pipeline_result

    async def fake_knowledge(repository_id):
        w.calls.append(("knowledge", repository_id))

    original_ensure_scanned = IndexingRunner._ensure_scanned

    async def ensure_scanned(self, job):
        if w.real_scan_check:
            await original_ensure_scanned(self, job)

    monkeypatch.setattr(runner_module, "run_parsing_pipeline", fake_pipeline)
    monkeypatch.setattr(runner_module, "run_knowledge_indexing_pipeline", fake_knowledge)
    monkeypatch.setattr(IndexingRunner, "_ensure_scanned", ensure_scanned)
    yield w
    for r in runners:
        await r.stop()
    async with factory() as session:
        await session.execute(delete(Repository).where(Repository.id.in_(created)))
        await session.commit()


class TestOutcomes:
    async def test_a_successful_job_is_marked_succeeded(self, world):
        repo = await world.repo()
        job_id = await world.job(repo)

        await world.runner()._drain()

        job = await world.get_job(job_id)
        assert (job.status, job.attempts, job.error) == ("succeeded", 1, None)
        assert world.calls == [("pipeline", repo)]

    async def test_a_stage_that_failed_without_raising_fails_the_job_without_retrying(self, world):
        repo = await world.repo()
        world.pipeline_result = "The hosted embedding service's daily free quota is used up."
        job_id = await world.job(repo)

        await world.runner()._drain()

        job = await world.get_job(job_id)
        assert (job.status, job.attempts) == ("failed", 1)  # a retry would hit the same quota
        assert "quota" in job.error

    async def test_an_unexpected_error_is_retried_then_succeeds(self, world, monkeypatch):
        # A real backoff, so the failed attempt waits instead of being re-claimed straight away.
        monkeypatch.setattr(get_settings().indexing, "indexing_retry_backoff_seconds", 1000)
        repo = await world.repo()
        job_id = await world.job(repo)
        world.pipeline_result = RuntimeError("network blip")
        runner = world.runner()

        await runner._drain()
        job = await world.get_job(job_id)
        assert (job.status, job.attempts) == ("queued", 1)
        assert "network blip" in job.error
        repository = await world.get_repo(repo)
        assert repository.indexing_status == "indexing" and "Retrying" in repository.error_message

        world.pipeline_result = None
        await world.sql("UPDATE indexing_jobs SET available_at = now() WHERE id = :id", id=job_id)
        await runner._drain()
        job = await world.get_job(job_id)
        assert (job.status, job.attempts) == ("succeeded", 2)

    async def test_the_last_attempt_fails_the_job_for_good(self, world):
        repo = await world.repo()
        job_id = await world.job(repo, max_attempts=1)
        world.pipeline_result = RuntimeError("still broken")

        await world.runner()._drain()

        job = await world.get_job(job_id)
        assert (job.status, job.attempts) == ("failed", 1)
        assert "still broken" in job.error

    async def test_a_clone_failure_is_not_retried(self, world, monkeypatch):
        repo = await world.repo(status="cloning", indexing_status="not_started")

        async def failing_clone(self, repository, *a, **kw):
            raise RepositoryCloneError("repository not found")

        monkeypatch.setattr(RepositoryService, "clone_and_scan", failing_clone)
        job_id = await world.job(repo)

        await world.runner()._drain()

        job = await world.get_job(job_id)
        assert (job.status, job.attempts) == ("failed", 1)
        assert "not found" in job.error
        assert world.calls == []  # never got as far as indexing

    async def test_a_queue_of_jobs_is_drained_in_order(self, world):
        repos = [await world.repo() for _ in range(3)]
        ids = [await world.job(r) for r in repos]

        await world.runner()._drain()

        assert [(await world.get_job(i)).status for i in ids] == ["succeeded"] * 3
        assert [call[1] for call in world.calls] == repos


class TestCloneStep:
    async def test_a_repository_still_cloning_is_cloned_with_the_jobs_limits_before_indexing(self, world, monkeypatch):
        repo = await world.repo(status="cloning", indexing_status="not_started")
        seen = {}

        async def clone(self, repository, max_files=None, max_bytes=None, *, publish_progress=False, begin_indexing=False):
            seen.update(files=max_files, bytes=max_bytes, publish=publish_progress, begin=begin_indexing)
            world.calls.append(("clone", repository.id))
            repository.status = "ready"
            repository.indexing_status = "indexing"

        monkeypatch.setattr(RepositoryService, "clone_and_scan", clone)
        job_id = await world.job(repo, max_files=1500, max_bytes=40 * 1024 * 1024)

        await world.runner()._drain()

        assert (await world.get_job(job_id)).status == "succeeded"
        assert [c[0] for c in world.calls] == ["clone", "pipeline"]  # clone first, then the pipeline
        assert seen == {"files": 1500, "bytes": 40 * 1024 * 1024, "publish": True, "begin": True}

    async def test_an_already_cloned_repository_is_not_cloned_again(self, world, monkeypatch):
        async def clone(*a, **kw):
            raise AssertionError("must not clone")

        monkeypatch.setattr(RepositoryService, "clone_and_scan", clone)
        repo = await world.repo(status="ready")
        job_id = await world.job(repo)

        await world.runner()._drain()

        assert (await world.get_job(job_id)).status == "succeeded"

    async def test_a_retry_after_a_crash_between_clone_and_scan_rescans_instead_of_indexing_nothing(
        self, world, monkeypatch
    ):
        scans = []

        async def scan(self, repository_id):
            scans.append(repository_id)

        monkeypatch.setattr(runner_module.WorkspaceService, "scan_repository", scan)
        world.real_scan_check = True
        repo = await world.repo(status="ready")  # cloned, but no workspace row: the scan never finished
        await world.job(repo)

        await world.runner()._drain()

        assert scans == [repo]


class TestKnowledgeReindex:
    async def test_runs_only_the_knowledge_stage(self, world):
        repo = await world.repo()
        job_id = await world.job(repo, kind="knowledge_reindex")

        await world.runner()._drain()

        assert (await world.get_job(job_id)).status == "succeeded"
        assert world.calls == [("knowledge", repo)]

    async def test_a_failed_knowledge_index_fails_the_job(self, world):
        repo = await world.repo()
        async with world.factory() as session:
            session.add(KnowledgeIndexState(repository_id=repo, status="failed", error_message="quota used up"))
            await session.commit()
        job_id = await world.job(repo, kind="knowledge_reindex")

        await world.runner()._drain()

        job = await world.get_job(job_id)
        assert (job.status, job.error) == ("failed", "quota used up")


class TestCancellation:
    async def test_a_job_cancelled_while_running_stops_at_the_next_stage_boundary(self, world, monkeypatch):
        repo = await world.repo()
        job_id = await world.job(repo)

        async def pipeline(repository_id, before_stage=None):
            await before_stage("parse")
            async with world.factory() as session:  # the user presses cancel mid-run
                await jobs.cancel_active(session, repo)
                await session.commit()
            await world.sql("UPDATE repositories SET indexing_status='failed', error_message=:m WHERE id=:id",
                            m=CANCEL_MESSAGE, id=repo)
            await before_stage("intelligence")
            world.calls.append(("ran past the boundary",))

        monkeypatch.setattr(runner_module, "run_parsing_pipeline", pipeline)

        await world.runner()._drain()

        assert world.calls == []
        assert (await world.get_job(job_id)).status == "cancelled"  # the worker did not overwrite it
        assert (await world.get_repo(repo)).indexing_status == "failed"

    async def test_a_cancel_during_the_last_stage_still_leaves_the_repository_failed(self, world, monkeypatch):
        repo = await world.repo()
        job_id = await world.job(repo)

        async def pipeline(repository_id, before_stage=None):
            await before_stage("knowledge")
            async with world.factory() as session:
                await jobs.cancel_active(session, repo)
                await session.commit()
            # ...but the final stage completes and marks the repository indexed after the cancel.
            await world.sql("UPDATE repositories SET indexing_status='indexed' WHERE id=:id", id=repo)

        monkeypatch.setattr(runner_module, "run_parsing_pipeline", pipeline)

        await world.runner()._drain()

        assert (await world.get_job(job_id)).status == "cancelled"
        repository = await world.get_repo(repo)
        assert (repository.indexing_status, repository.error_message) == ("failed", CANCEL_MESSAGE)

    async def test_a_clone_that_finishes_after_cancel_does_not_leave_the_repository_stuck_indexing(
        self, world, monkeypatch
    ):
        repo = await world.repo(status="cloning", indexing_status="not_started")

        async def clone(self, repository, *a, **kw):
            async with world.factory() as session:  # cancelled while the (uninterruptible) clone runs
                await jobs.cancel_active(session, repo)
                await session.commit()
            await world.sql("UPDATE repositories SET status='ready', indexing_status='indexing' WHERE id=:id", id=repo)

        monkeypatch.setattr(RepositoryService, "clone_and_scan", clone)
        job_id = await world.job(repo)

        await world.runner()._drain()

        assert world.calls == []  # the pipeline never started
        assert (await world.get_job(job_id)).status == "cancelled"
        repository = await world.get_repo(repo)
        assert (repository.indexing_status, repository.error_message) == ("failed", CANCEL_MESSAGE)

    async def test_a_worker_that_lost_its_job_to_another_stops_without_touching_the_repository(self, world, monkeypatch):
        repo = await world.repo()
        job_id = await world.job(repo)

        async def pipeline(repository_id, before_stage=None):
            await before_stage("parse")
            await world.sql("UPDATE indexing_jobs SET claimed_by = 'someone-else' WHERE id = :id", id=job_id)
            await before_stage("intelligence")

        monkeypatch.setattr(runner_module, "run_parsing_pipeline", pipeline)

        await world.runner()._drain()

        job = await world.get_job(job_id)
        assert (job.status, job.claimed_by) == ("running", "someone-else")  # theirs now; we did not finish it
        assert (await world.get_repo(repo)).indexing_status == "indexing"


class TestLeases:
    async def test_the_lease_is_renewed_while_a_job_runs(self, world, monkeypatch):
        repo = await world.repo()
        job_id = await world.job(repo)
        started = {}

        async def slow(repository_id, before_stage=None):
            started["lease"] = (await world.get_job(job_id)).lease_expires_at
            await asyncio.sleep(0.4)
            started["renewed"] = (await world.get_job(job_id)).lease_expires_at

        monkeypatch.setattr(runner_module, "run_parsing_pipeline", slow)

        await world.runner()._drain()

        assert started["renewed"] > started["lease"]

    async def test_a_job_abandoned_with_no_attempts_left_marks_its_repository_failed(self, world):
        repo = await world.repo()
        job_id = await world.job(repo, max_attempts=1)
        async with world.factory() as session:  # a worker took it and died
            await jobs.claim_next(session, "dead-worker", 60)
            await session.commit()
        await world.sql("UPDATE indexing_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :id", id=job_id)

        await world.runner()._drain()

        assert (await world.get_job(job_id)).status == "failed"
        repository = await world.get_repo(repo)
        assert repository.indexing_status == "failed" and "stopping" in repository.error_message

    async def test_a_job_taken_over_from_a_dead_worker_is_run_to_completion(self, world):
        repo = await world.repo()
        job_id = await world.job(repo)
        async with world.factory() as session:
            await jobs.claim_next(session, "dead-worker", 60)
            await session.commit()
        await world.sql("UPDATE indexing_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :id", id=job_id)

        await world.runner("rescuer")._drain()

        job = await world.get_job(job_id)
        assert (job.status, job.attempts) == ("succeeded", 2)


class TestWakeDrivenLoop:
    async def test_the_loop_sleeps_until_woken_and_never_polls(self, world):
        runner = world.runner()
        runner.start()  # one immediate pass finds nothing
        await asyncio.sleep(0.2)

        repo = await world.repo()
        job_id = await world.job(repo)
        await asyncio.sleep(1.0)  # no wake: an idle loop must not notice the new job on its own
        assert (await world.get_job(job_id)).status == "queued"

        runner.wake()
        assert (await world.wait_for(job_id, "succeeded")).attempts == 1

    async def test_a_retry_is_picked_up_by_its_own_timer_without_any_wake(self, world, monkeypatch):
        # One real second of backoff: the retry is not claimable at first, so only the timer can bring it back.
        monkeypatch.setattr(get_settings().indexing, "indexing_retry_backoff_seconds", 1)
        repo = await world.repo()
        world.pipeline_result = RuntimeError("flaky")
        job_id = await world.job(repo)
        runner = world.runner()
        runner.start()

        # Wait for the first attempt to fail and be requeued. (A new job is also "queued", so wait on the error.)
        for _ in range(100):
            job = await world.get_job(job_id)
            if job.error and "flaky" in job.error:
                break
            await asyncio.sleep(0.05)
        assert job.status == "queued" and job.attempts == 1
        world.pipeline_result = None  # the next attempt will succeed
        job = await world.wait_for(job_id, "succeeded", timeout=8.0)

        assert job.attempts == 2

    async def test_stopping_hands_the_running_job_back_with_its_attempt_refunded(self, world, monkeypatch):
        repo = await world.repo()
        job_id = await world.job(repo)
        entered = asyncio.Event()

        async def blocked(repository_id, before_stage=None):
            entered.set()
            await asyncio.sleep(60)

        monkeypatch.setattr(runner_module, "run_parsing_pipeline", blocked)
        runner = world.runner()
        runner.start()
        await asyncio.wait_for(entered.wait(), 5)
        assert runner.status()["running_job_id"] == str(job_id)

        await runner.stop()

        job = await world.get_job(job_id)
        assert (job.status, job.attempts, job.claimed_by) == ("queued", 0, None)  # a deploy is not the job's fault

    async def test_status_reports_idle_when_nothing_is_running(self, world):
        assert world.runner().status() == {"worker_id": "test-worker", "running_job_id": None, "running_repository_id": None}
