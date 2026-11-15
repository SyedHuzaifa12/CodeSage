"""The indexing worker: claims jobs from the Postgres queue and runs them (ADR-028).

It runs inside the indexer process (``ROLE=indexer``, or ``ROLE=all``) as one
background asyncio task. It never polls while idle — that would burn the
free Neon database's compute hours. It sleeps until something calls
:meth:`IndexingRunner.wake` (the API's ``/internal/wake``), drains every
claimable job, then sleeps again, scheduling at most one timer for the
moment a retry's backoff ends or a dead worker's lease lapses.

Everything runs on the process's single event loop, like the API does,
because the Postgres/Redis/Qdrant clients are cached per process and bound
to the loop that created them. The blocking steps (git clone, directory
walks, embedding calls) are pushed to threads where they live, so health
checks and wake calls stay responsive while a job runs.
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from dataclasses import dataclass
from typing import Optional

from app.core.config import Settings, get_settings
from app.db.postgres import get_session_factory
from app.indexing import repository as jobs
from app.ingestion.exceptions import IndexingCancelledError
from app.ingestion.parsing_service import StageHook, run_parsing_pipeline
from app.ingestion.service import WorkspaceService
from app.knowledge import repository as knowledge_db
from app.knowledge.pipeline import run_knowledge_indexing_pipeline
from app.repository import repository as repository_db
from app.repository.exceptions import RepositoryCloneError, RepositoryTooLargeError
from app.repository.service import RepositoryService

logger = logging.getLogger("codesage.indexing.runner")

# Failures a retry cannot fix: the repository is unreachable or too big, and will still be.
_NOT_RETRYABLE = (RepositoryCloneError, RepositoryTooLargeError)
_CANCEL_MESSAGE = "Indexing was cancelled by request."
_CRASH_RECOVERY_WAKE_SECONDS = 30


@dataclass(frozen=True)
class ClaimedJob:
    """The fields of a claimed job the runner needs, copied out so no ORM state outlives its session."""

    id: uuid.UUID
    repository_id: uuid.UUID
    kind: str
    attempts: int
    max_attempts: int
    max_files: Optional[int]
    max_bytes: Optional[int]


def _new_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"


class IndexingRunner:
    """Claims and executes indexing jobs until stopped."""

    def __init__(self, settings: Optional[Settings] = None, worker_id: Optional[str] = None) -> None:
        self._settings = settings or get_settings()
        self.worker_id = worker_id or _new_worker_id()
        self._wake_event: Optional[asyncio.Event] = None
        self._task: Optional[asyncio.Task] = None
        self._timers: list[asyncio.TimerHandle] = []
        self._stopping = False
        self._current: Optional[ClaimedJob] = None

    # -- lifecycle ---------------------------------------------------------------------------

    def start(self) -> None:
        """Start the claim loop and run one immediate pass (picks up jobs left by a previous instance)."""
        self._wake_event = asyncio.Event()
        self._stopping = False
        self._task = asyncio.create_task(self._loop(), name=f"indexing-runner-{self.worker_id}")
        self.wake()
        logger.info("Indexing runner %s started", self.worker_id)

    async def stop(self) -> None:
        """Stop the loop. A job still running goes straight back to the queue (attempt refunded)."""
        self._stopping = True
        for timer in self._timers:
            timer.cancel()
        self._timers.clear()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        try:
            async with get_session_factory()() as session:
                released = await jobs.release_owned(session, self.worker_id)
                await session.commit()
            if released:
                logger.info("Indexing runner %s returned %d running job(s) to the queue", self.worker_id, released)
        except Exception:  # noqa: BLE001 -- shutting down; the lease will expire and another worker takes over
            logger.warning("Could not release running jobs on shutdown; their leases will expire.", exc_info=True)

    def wake(self) -> None:
        """Ask the loop to look for work. Safe to call repeatedly; wakes coalesce."""
        if self._wake_event is not None:
            self._wake_event.set()

    def status(self) -> dict:
        """What this worker is doing now (served by ``/internal/heartbeat``)."""
        return {
            "worker_id": self.worker_id,
            "running_job_id": str(self._current.id) if self._current else None,
            "running_repository_id": str(self._current.repository_id) if self._current else None,
        }

    def _schedule_wake(self, delay_seconds: float) -> None:
        if self._stopping:
            return
        loop = asyncio.get_running_loop()
        self._timers = [t for t in self._timers if not t.cancelled() and t.when() > loop.time()]
        self._timers.append(loop.call_later(max(delay_seconds, 0.0), self.wake))

    # -- the loop ----------------------------------------------------------------------------

    async def _loop(self) -> None:
        assert self._wake_event is not None
        while not self._stopping:
            await self._wake_event.wait()
            self._wake_event.clear()
            if self._stopping:
                break
            try:
                await self._drain()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 -- the loop must survive anything a single pass throws
                logger.exception("Indexing runner pass failed; will look again shortly")
                self._schedule_wake(_CRASH_RECOVERY_WAKE_SECONDS)

    async def _drain(self) -> None:
        while not self._stopping:
            job = await self._claim()
            if job is None:
                await self._schedule_next_wake()
                return
            await self._execute(job)

    async def _claim(self) -> Optional[ClaimedJob]:
        cfg = self._settings.indexing
        async with get_session_factory()() as session:
            for repository_id in await jobs.reap_exhausted(session):
                await self._set_repository_failed(session, repository_id, "The indexing worker kept stopping while running this job.")
            row = await jobs.claim_next(session, self.worker_id, cfg.indexing_lease_seconds)
            claimed = (
                ClaimedJob(
                    id=row.id, repository_id=row.repository_id, kind=row.kind, attempts=row.attempts,
                    max_attempts=row.max_attempts, max_files=row.max_files, max_bytes=row.max_bytes,
                )
                if row is not None
                else None
            )
            await session.commit()
        return claimed

    async def _schedule_next_wake(self) -> None:
        async with get_session_factory()() as session:
            wait = await jobs.seconds_until_next_work(session)
        if wait is not None:
            self._schedule_wake(wait + 1)  # +1s so the lease/backoff has really lapsed when we look

    # -- running one job ---------------------------------------------------------------------

    async def _execute(self, job: ClaimedJob) -> None:
        self._current = job
        lease_task = asyncio.create_task(self._keep_lease(job))
        logger.info("Job %s (%s) for repository %s started, attempt %d/%d",
                    job.id, job.kind, job.repository_id, job.attempts, job.max_attempts)
        try:
            failure = await self._run(job)
            if failure:
                await self._finish(job, "failed", failure)
            else:
                await self._finish(job, "succeeded", None)
        except IndexingCancelledError as exc:
            logger.info("Job %s stopped: %s", job.id, exc)
            await self._reassert_cancel(job)
        except _NOT_RETRYABLE as exc:
            await self._finish(job, "failed", str(exc))
        except Exception as exc:  # noqa: BLE001 -- anything else gets a bounded retry
            logger.exception("Job %s failed on attempt %d/%d", job.id, job.attempts, job.max_attempts)
            await self._retry_or_fail(job, exc)
        finally:
            lease_task.cancel()
            self._current = None

    async def _run(self, job: ClaimedJob) -> Optional[str]:
        """Do the work; return a failure message for a stage that failed without raising."""
        async with get_session_factory()() as session:
            repository = await repository_db.get_by_id(session, job.repository_id)
        if repository is None:
            raise IndexingCancelledError("the repository was deleted")

        if job.kind == "knowledge_reindex":
            await self._gate(job)
            await run_knowledge_indexing_pipeline(job.repository_id)
            async with get_session_factory()() as session:
                state = await knowledge_db.get_index_state(session, job.repository_id)
            if state is not None and state.status == "failed":
                return state.error_message or "Knowledge indexing failed."
            return None

        await self._gate(job)
        if repository.status != "ready":
            await self._clone(job)
            await self._gate(job)  # a clone cannot be interrupted, so check again before going on
        else:
            await self._ensure_scanned(job)
        return await run_parsing_pipeline(job.repository_id, before_stage=self._stage_hook(job))

    async def _clone(self, job: ClaimedJob) -> None:
        async with get_session_factory()() as session:
            repository = await repository_db.get_by_id(session, job.repository_id)
            service = RepositoryService(session, self._settings, WorkspaceService(session))
            await service.clone_and_scan(
                repository, job.max_files, job.max_bytes, publish_progress=True, begin_indexing=True
            )
            await session.commit()

    async def _ensure_scanned(self, job: ClaimedJob) -> None:
        """Re-scan if a previous attempt died after the clone but before the scan finished.

        Without this a retry would see ``ready`` and index an empty file list.
        """
        from app.ingestion import repository as ingestion_db  # local: avoids widening the module's import surface

        async with get_session_factory()() as session:
            workspace = await ingestion_db.get_workspace(session, job.repository_id)
            if workspace is None or workspace.status != "ready":
                await WorkspaceService(session).scan_repository(job.repository_id)
                await session.commit()

    def _stage_hook(self, job: ClaimedJob) -> StageHook:
        async def hook(stage: str) -> None:
            await self._gate(job)

        return hook

    async def _gate(self, job: ClaimedJob) -> None:
        """Stop here if the job was cancelled or taken over by another worker."""
        async with get_session_factory()() as session:
            if not await jobs.owns_running_job(session, job.id, self.worker_id):
                raise IndexingCancelledError("the job was cancelled or reassigned")

    async def _keep_lease(self, job: ClaimedJob) -> None:
        cfg = self._settings.indexing
        while True:
            await asyncio.sleep(cfg.indexing_heartbeat_seconds)
            try:
                async with get_session_factory()() as session:
                    owned = await jobs.renew_lease(session, job.id, self.worker_id, cfg.indexing_lease_seconds)
                    await session.commit()
            except Exception:  # noqa: BLE001 -- one missed beat is fine; the lease has slack
                logger.warning("Could not renew the lease for job %s", job.id, exc_info=True)
                continue
            if not owned:
                logger.warning("Job %s is no longer owned by this worker; it will stop at the next stage boundary", job.id)
                return

    # -- outcomes ----------------------------------------------------------------------------

    async def _finish(self, job: ClaimedJob, status: str, error: Optional[str]) -> None:
        async with get_session_factory()() as session:
            applied = await jobs.finish(session, job.id, self.worker_id, status, error)
            await session.commit()
        if not applied:
            await self._reassert_cancel(job)  # cancelled (or taken over) while we were finishing
        logger.info("Job %s %s%s", job.id, status if applied else "ended (no longer owned)", f": {error}" if error else "")

    async def _reassert_cancel(self, job: ClaimedJob) -> None:
        """If the job was cancelled, make the repository say so.

        Work that was already in flight when the user cancelled (a clone cannot be interrupted;
        the last stage may finish) can overwrite the repository's state afterwards, leaving it
        showing "indexing" with no job behind it. A job taken over by another worker is left alone.
        """
        async with get_session_factory()() as session:
            current = await jobs.get_job(session, job.id)
            if current is not None and current.status == "cancelled":
                await self._set_repository_failed(session, job.repository_id, _CANCEL_MESSAGE)
            await session.commit()

    async def _retry_or_fail(self, job: ClaimedJob, exc: Exception) -> None:
        cfg = self._settings.indexing
        message = f"{type(exc).__name__}: {exc}"[:500]
        if job.attempts >= job.max_attempts:
            await self._finish(job, "failed", message)
            return
        delay = cfg.indexing_retry_backoff_seconds * job.attempts
        async with get_session_factory()() as session:
            if await jobs.requeue_for_retry(session, job.id, self.worker_id, message, delay):
                repository = await repository_db.get_by_id(session, job.repository_id)
                if repository is not None and repository.status == "ready":
                    # The pipeline marked it failed on the way out; it is going to be retried, so say so.
                    repository.indexing_status = "indexing"
                    repository.error_message = f"Retrying after an error: {message}"
                    await repository_db.save(session, repository)
            await session.commit()
        logger.warning("Job %s will retry in %ds (attempt %d/%d failed)", job.id, delay, job.attempts, job.max_attempts)
        self._schedule_wake(delay + 1)

    @staticmethod
    async def _set_repository_failed(session, repository_id: uuid.UUID, message: str) -> None:
        repository = await repository_db.get_by_id(session, repository_id)
        if repository is not None:
            repository.indexing_status = "failed"
            repository.error_message = message
            await repository_db.save(session, repository)

