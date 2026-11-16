"""Integration tests for the Postgres job queue (ADR-028).

These need a real Postgres: the guarantees under test (``FOR UPDATE SKIP LOCKED``
claiming, the partial unique index, lease takeover) are database behaviour that
a fake cannot demonstrate. Skipped, not failed, when Postgres is unreachable or
``indexing_jobs`` has not been migrated.
"""
from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text

from app.db.postgres import check_postgres_connection, get_session_factory
from app.indexing import repository as jobs
from app.ingestion.exceptions import IndexingAlreadyInProgressError
from app.models.indexing_job import IndexingJob
from app.models.repository import Repository

LEASE = 60


@pytest_asyncio.fixture
async def queue():
    """Yields a helper bound to a clean slate; removes everything the test created."""
    if not await check_postgres_connection():
        pytest.skip("Postgres unreachable.")
    factory = get_session_factory()
    try:
        async with factory() as session:
            others = (
                await session.execute(
                    select(func.count()).select_from(IndexingJob).where(IndexingJob.status.in_(("queued", "running")))
                )
            ).scalar_one()
    except Exception:  # noqa: BLE001 -- table missing => migration not applied
        pytest.skip("`alembic upgrade head` not applied (indexing_jobs missing).")
    if others:
        pytest.skip("Other active indexing jobs exist in this database; claim tests would race with them.")

    created: list[uuid.UUID] = []

    class Helper:
        factory = staticmethod(get_session_factory())

        async def repo(self) -> uuid.UUID:
            async with factory() as session:
                repository = Repository(name="q", github_url=f"https://github.com/o/{uuid.uuid4().hex[:8]}",
                                        local_path="", status="ready")
                session.add(repository)
                await session.commit()
                created.append(repository.id)
                return repository.id

        async def enqueue(self, repository_id, kind="full_index", max_attempts=3, **kw) -> uuid.UUID:
            async with factory() as session:
                job = await jobs.enqueue(session, repository_id, kind, max_attempts=max_attempts, **kw)
                await session.commit()
                return job.id

        async def get(self, job_id) -> IndexingJob:
            async with factory() as session:
                return await jobs.get_job(session, job_id)

        async def claim(self, worker="w1"):
            async with factory() as session:
                job = await jobs.claim_next(session, worker, LEASE)
                await session.commit()
                return job

        async def sql(self, statement: str, **params):
            async with factory() as session:
                result = await session.execute(text(statement), params)
                await session.commit()
                return result

    yield Helper()
    async with factory() as session:
        await session.execute(delete(Repository).where(Repository.id.in_(created)))  # jobs cascade
        await session.commit()


class TestEnqueue:
    async def test_creates_a_queued_job(self, queue):
        repo = await queue.repo()
        job = await queue.get(await queue.enqueue(repo, max_files=10, max_bytes=2048))
        assert (job.status, job.attempts, job.kind) == ("queued", 0, "full_index")
        assert (job.max_files, job.max_bytes) == (10, 2048)

    async def test_a_second_active_job_for_the_same_repository_is_refused(self, queue):
        repo = await queue.repo()
        await queue.enqueue(repo)
        with pytest.raises(IndexingAlreadyInProgressError):
            await queue.enqueue(repo, kind="knowledge_reindex")

    async def test_the_refusal_does_not_poison_the_callers_transaction(self, queue):
        repo, other = await queue.repo(), await queue.repo()
        await queue.enqueue(repo)
        async with queue.factory() as session:
            with pytest.raises(IndexingAlreadyInProgressError):
                await jobs.enqueue(session, repo, "full_index", max_attempts=3)
            await jobs.enqueue(session, other, "full_index", max_attempts=3)  # same session, still usable
            await session.commit()

    async def test_a_new_job_is_allowed_once_the_previous_one_is_finished(self, queue):
        repo = await queue.repo()
        first = await queue.enqueue(repo)
        claimed = await queue.claim()
        async with queue.factory() as session:
            assert await jobs.finish(session, claimed.id, "w1", "succeeded", None)
            await session.commit()
        second = await queue.enqueue(repo)
        assert first != second

    async def test_different_repositories_can_each_have_an_active_job(self, queue):
        await queue.enqueue(await queue.repo())
        await queue.enqueue(await queue.repo())

    async def test_deleting_the_repository_deletes_its_jobs(self, queue):
        repo = await queue.repo()
        job_id = await queue.enqueue(repo)
        await queue.sql("DELETE FROM repositories WHERE id = :id", id=repo)
        assert await queue.get(job_id) is None


class TestClaiming:
    async def test_claims_the_oldest_job_and_marks_it_running(self, queue):
        first = await queue.enqueue(await queue.repo())
        await queue.enqueue(await queue.repo())

        job = await queue.claim("worker-a")

        assert job.id == first
        assert (job.status, job.attempts, job.claimed_by) == ("running", 1, "worker-a")
        assert job.lease_expires_at is not None and job.started_at is not None

    async def test_returns_none_when_the_queue_is_empty(self, queue):
        assert await queue.claim() is None

    async def test_a_running_job_with_a_live_lease_is_not_claimable(self, queue):
        await queue.enqueue(await queue.repo())
        assert await queue.claim("a") is not None
        assert await queue.claim("b") is None

    async def test_concurrent_workers_never_claim_the_same_job(self, queue):
        ids = {await queue.enqueue(await queue.repo()) for _ in range(6)}

        async def worker(name):
            got = []
            while (job := await queue.claim(name)) is not None:
                got.append(job.id)
            return got

        results = await asyncio.gather(*(worker(f"w{i}") for i in range(4)))
        claimed = [job_id for part in results for job_id in part]

        assert sorted(claimed) == sorted(ids)  # every job claimed exactly once
        assert len(claimed) == len(set(claimed))

    async def test_a_job_whose_lease_lapsed_is_taken_over_by_another_worker(self, queue):
        job_id = await queue.enqueue(await queue.repo())
        await queue.claim("dead-worker")
        await queue.sql("UPDATE indexing_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :id", id=job_id)

        job = await queue.claim("new-worker")

        assert job.id == job_id and job.claimed_by == "new-worker" and job.attempts == 2

    async def test_a_job_waiting_out_a_retry_backoff_is_not_claimable_yet(self, queue):
        job_id = await queue.enqueue(await queue.repo())
        await queue.claim("a")
        async with queue.factory() as session:
            assert await jobs.requeue_for_retry(session, job_id, "a", "boom", delay_seconds=300)
            await session.commit()

        assert await queue.claim("b") is None
        async with queue.factory() as session:
            wait = await jobs.seconds_until_next_work(session)
        assert 250 < wait <= 300  # the runner can sleep exactly this long instead of polling


class TestLeases:
    async def test_the_owner_can_renew_but_a_stranger_cannot(self, queue):
        await queue.enqueue(await queue.repo())
        job = await queue.claim("owner")
        async with queue.factory() as session:
            assert await jobs.renew_lease(session, job.id, "owner", 600)
            assert not await jobs.renew_lease(session, job.id, "stranger", 600)
            await session.commit()
        assert (await queue.get(job.id)).lease_expires_at > job.lease_expires_at

    async def test_a_worker_that_lost_its_job_to_a_takeover_cannot_renew_or_finish_it(self, queue):
        job_id = await queue.enqueue(await queue.repo())
        await queue.claim("slow")
        await queue.sql("UPDATE indexing_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :id", id=job_id)
        await queue.claim("fast")

        async with queue.factory() as session:
            assert not await jobs.renew_lease(session, job_id, "slow", LEASE)
            assert not await jobs.finish(session, job_id, "slow", "succeeded", None)
            assert not await jobs.owns_running_job(session, job_id, "slow")
            assert await jobs.owns_running_job(session, job_id, "fast")

    async def test_a_job_that_keeps_losing_its_worker_is_failed_not_retried_forever(self, queue):
        repo = await queue.repo()
        job_id = await queue.enqueue(repo, max_attempts=1)
        await queue.claim("w")  # attempts == max_attempts
        await queue.sql("UPDATE indexing_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = :id", id=job_id)

        assert await queue.claim("other") is None  # not claimable: no attempts left
        async with queue.factory() as session:
            reaped = await jobs.reap_exhausted(session)
            await session.commit()

        assert reaped == [repo]
        job = await queue.get(job_id)
        assert job.status == "failed" and "stopped responding" in job.error


class TestFinishing:
    async def test_finish_records_the_outcome(self, queue):
        await queue.enqueue(await queue.repo())
        job = await queue.claim("w")
        async with queue.factory() as session:
            assert await jobs.finish(session, job.id, "w", "failed", "clone failed")
            await session.commit()
        done = await queue.get(job.id)
        assert (done.status, done.error) == ("failed", "clone failed")
        assert done.finished_at is not None and done.lease_expires_at is None

    async def test_a_cancelled_job_stays_cancelled_when_the_worker_finishes_anyway(self, queue):
        repo = await queue.repo()
        await queue.enqueue(repo)
        job = await queue.claim("w")
        async with queue.factory() as session:
            assert await jobs.cancel_active(session, repo)
            await session.commit()

        async with queue.factory() as session:
            assert not await jobs.finish(session, job.id, "w", "succeeded", None)
            assert not await jobs.owns_running_job(session, job.id, "w")  # the runner's stage-boundary check sees this
        assert (await queue.get(job.id)).status == "cancelled"

    async def test_cancelling_a_queued_job_removes_it_from_the_queue(self, queue):
        repo = await queue.repo()
        await queue.enqueue(repo)
        async with queue.factory() as session:
            assert await jobs.cancel_active(session, repo)
            assert not await jobs.cancel_active(session, repo)  # nothing left to cancel
            await session.commit()
        assert await queue.claim() is None

    async def test_requeue_keeps_the_error_for_diagnosis(self, queue):
        job_id = await queue.enqueue(await queue.repo())
        await queue.claim("w")
        async with queue.factory() as session:
            await jobs.requeue_for_retry(session, job_id, "w", "network blip", 0)
            await session.commit()
        job = await queue.get(job_id)
        assert (job.status, job.error, job.claimed_by) == ("queued", "network blip", None)

    async def test_graceful_shutdown_returns_the_job_and_refunds_the_attempt(self, queue):
        job_id = await queue.enqueue(await queue.repo())
        await queue.claim("host-being-redeployed")
        async with queue.factory() as session:
            assert await jobs.release_owned(session, "host-being-redeployed") == 1
            await session.commit()

        job = await queue.get(job_id)
        assert (job.status, job.attempts, job.claimed_by) == ("queued", 0, None)
        assert (await queue.claim("replacement")).id == job_id


class TestNextWork:
    async def test_nothing_pending_means_no_wakeup_is_scheduled(self, queue):
        async with queue.factory() as session:
            assert await jobs.seconds_until_next_work(session) is None

    async def test_a_running_jobs_lease_expiry_is_the_next_wakeup(self, queue):
        await queue.enqueue(await queue.repo())
        await queue.claim("w")
        async with queue.factory() as session:
            wait = await jobs.seconds_until_next_work(session)
        assert LEASE - 5 < wait <= LEASE


class TestCancelWhileTheJobHoldsTheRepositoryRow:
    """The indexing pipeline keeps one transaction open (holding the repository row's lock) until it finishes.
    A cancel request must still return promptly and must still reach the indexer."""

    async def test_cancel_returns_promptly_and_the_job_is_cancelled_for_the_indexer(self, queue, monkeypatch):
        import time

        from app.core.config import get_settings
        from app.ingestion.service import WorkspaceService

        # (Without this the Celery branch runs, and it blocks on the row lock exactly as described above.)
        monkeypatch.setattr(get_settings().indexing, "indexing_backend", "postgres")

        repo = await queue.repo()
        await queue.sql("UPDATE repositories SET indexing_status = 'indexing' WHERE id = :id", id=repo)
        job_id = await queue.enqueue(repo)
        await queue.claim("indexer")

        async with queue.factory() as pipeline_txn:  # what the running pipeline does: lock the row, stay open
            await pipeline_txn.execute(text("SELECT id FROM repositories WHERE id = :id FOR UPDATE"), {"id": repo})

            async with queue.factory() as request_session:
                started = time.perf_counter()
                result = await WorkspaceService(request_session).cancel_indexing(repo)
                elapsed = time.perf_counter() - started
                await request_session.commit()

            assert elapsed < 5, f"cancel blocked for {elapsed:.1f}s on the pipeline's row lock"
            assert (result.indexing_status, result.error_message) == ("failed", "Indexing was cancelled by request.")
            # The indexer's stage-boundary check reads this from another connection, while the lock is still held:
            assert (await queue.get(job_id)).status == "cancelled"
            async with queue.factory() as session:
                assert not await jobs.owns_running_job(session, job_id, "indexer")
            await pipeline_txn.rollback()  # the pipeline reaches its boundary, stops, and releases the row
