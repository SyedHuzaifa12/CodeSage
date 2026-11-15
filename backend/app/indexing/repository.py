"""Data access for the Postgres job queue (ADR-028).

Every function takes the caller's session and never commits; the caller
decides the transaction boundary. All time arithmetic uses the database
clock (``now()``), never the application host's, because the API, the
indexer and Postgres run on different machines whose clocks can differ.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.exceptions import IndexingAlreadyInProgressError
from app.models.indexing_job import ACTIVE_JOB_STATUSES, IndexingJob

_REAPED_MESSAGE = "The indexing worker stopped responding repeatedly while running this job."

# Claim = take the oldest claimable job, atomically. SKIP LOCKED lets several
# workers claim concurrently without ever waiting on, or double-taking, a row.
# Claimable: queued, or "running" whose lease lapsed (its worker died).
_CLAIM_SQL = text(
    """
    UPDATE indexing_jobs
    SET status = 'running',
        attempts = attempts + 1,
        claimed_by = :worker,
        lease_expires_at = now() + make_interval(secs => CAST(:lease AS double precision)),
        heartbeat_at = now(),
        started_at = COALESCE(started_at, now()),
        updated_at = now()
    WHERE id = (
        SELECT id FROM indexing_jobs
        WHERE attempts < max_attempts
          AND available_at <= now()
          AND (status = 'queued' OR (status = 'running' AND lease_expires_at < now()))
        ORDER BY created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id
    """
)

# A job whose lease lapsed with no attempts left is finished for good.
_REAP_SQL = text(
    """
    UPDATE indexing_jobs
    SET status = 'failed', finished_at = now(), error = :message, updated_at = now()
    WHERE status = 'running' AND lease_expires_at < now() AND attempts >= max_attempts
    RETURNING repository_id
    """
)

# Seconds until something *will become* claimable (a retry's backoff ending, or a
# running job's lease lapsing). Lets the runner sleep exactly that long instead of polling.
_NEXT_DELAY_SQL = text(
    """
    SELECT EXTRACT(EPOCH FROM (MIN(t) - now())) FROM (
        SELECT available_at AS t FROM indexing_jobs WHERE status = 'queued' AND attempts < max_attempts
        UNION ALL
        SELECT lease_expires_at AS t FROM indexing_jobs WHERE status = 'running' AND lease_expires_at IS NOT NULL
    ) pending
    """
)


async def enqueue(
    session: AsyncSession,
    repository_id: uuid.UUID,
    kind: str,
    *,
    max_attempts: int,
    max_files: Optional[int] = None,
    max_bytes: Optional[int] = None,
) -> IndexingJob:
    """Create a queued job, refusing if the repository already has an active one.

    Args:
        session: The caller's session (not committed here).
        repository_id: The repository to index.
        kind: ``full_index`` or ``knowledge_reindex``.
        max_attempts: Total tries allowed (first run plus retries).
        max_files: Guest clone cap, used only if the job has to clone first.
        max_bytes: Guest clone size cap, same condition.

    Returns:
        The persisted job.

    Raises:
        IndexingAlreadyInProgressError: If an active job already exists (the
            partial unique index is what makes this race-free).
    """
    job = IndexingJob(
        repository_id=repository_id, kind=kind, status="queued", max_attempts=max_attempts,
        max_files=max_files, max_bytes=max_bytes,
    )
    try:
        # A savepoint, so the unique violation does not poison the caller's transaction.
        async with session.begin_nested():
            session.add(job)
            await session.flush()
    except IntegrityError as exc:
        raise IndexingAlreadyInProgressError(
            f"Repository '{repository_id}' already has an indexing job queued or running."
        ) from exc
    return job


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> Optional[IndexingJob]:
    """Fetch a job by id, bypassing the session's identity map so the state is current."""
    result = await session.execute(
        select(IndexingJob).where(IndexingJob.id == job_id).execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def get_active_job(session: AsyncSession, repository_id: uuid.UUID) -> Optional[IndexingJob]:
    """Fetch the repository's queued/running job, if any."""
    result = await session.execute(
        select(IndexingJob)
        .where(IndexingJob.repository_id == repository_id, IndexingJob.status.in_(ACTIVE_JOB_STATUSES))
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


async def claim_next(session: AsyncSession, worker_id: str, lease_seconds: int) -> Optional[IndexingJob]:
    """Atomically claim the oldest claimable job for ``worker_id``, or ``None``."""
    job_id = (await session.execute(_CLAIM_SQL, {"worker": worker_id, "lease": lease_seconds})).scalar_one_or_none()
    return await get_job(session, job_id) if job_id else None


async def reap_exhausted(session: AsyncSession) -> list[uuid.UUID]:
    """Fail jobs whose worker kept dying; returns the affected repository ids."""
    rows = await session.execute(_REAP_SQL, {"message": _REAPED_MESSAGE})
    return [row[0] for row in rows.all()]


async def renew_lease(session: AsyncSession, job_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
    """Extend ``worker_id``'s lease. ``False`` means the job is no longer this worker's to run."""
    result = await session.execute(
        text(
            """
            UPDATE indexing_jobs
            SET heartbeat_at = now(), updated_at = now(),
                lease_expires_at = now() + make_interval(secs => CAST(:lease AS double precision))
            WHERE id = :id AND claimed_by = :worker AND status = 'running'
            """
        ),
        {"id": job_id, "worker": worker_id, "lease": lease_seconds},
    )
    return result.rowcount > 0


async def owns_running_job(session: AsyncSession, job_id: uuid.UUID, worker_id: str) -> bool:
    """Whether the job is still running under ``worker_id`` (not cancelled, not taken over)."""
    job = await get_job(session, job_id)
    return job is not None and job.status == "running" and job.claimed_by == worker_id


async def finish(session: AsyncSession, job_id: uuid.UUID, worker_id: str, status: str, error: Optional[str]) -> bool:
    """Mark the job finished — only if ``worker_id`` still owns it (a cancelled job stays cancelled)."""
    result = await session.execute(
        text(
            """
            UPDATE indexing_jobs
            SET status = :status, error = :error, finished_at = now(), updated_at = now(),
                lease_expires_at = NULL
            WHERE id = :id AND claimed_by = :worker AND status = 'running'
            """
        ),
        {"id": job_id, "worker": worker_id, "status": status, "error": error},
    )
    return result.rowcount > 0


async def requeue_for_retry(
    session: AsyncSession, job_id: uuid.UUID, worker_id: str, error: str, delay_seconds: float
) -> bool:
    """Put a failed attempt back in the queue, claimable after ``delay_seconds``."""
    result = await session.execute(
        text(
            """
            UPDATE indexing_jobs
            SET status = 'queued', error = :error, claimed_by = NULL, lease_expires_at = NULL, updated_at = now(),
                available_at = now() + make_interval(secs => CAST(:delay AS double precision))
            WHERE id = :id AND claimed_by = :worker AND status = 'running'
            """
        ),
        {"id": job_id, "worker": worker_id, "error": error, "delay": delay_seconds},
    )
    return result.rowcount > 0


async def release_owned(session: AsyncSession, worker_id: str) -> int:
    """On graceful shutdown, hand this worker's running jobs straight back to the queue.

    The attempt is refunded: a deploy restarting the host is not the job's fault, and
    must not burn its retry budget.
    """
    result = await session.execute(
        text(
            """
            UPDATE indexing_jobs
            SET status = 'queued', claimed_by = NULL, lease_expires_at = NULL, updated_at = now(),
                attempts = GREATEST(attempts - 1, 0), available_at = now()
            WHERE claimed_by = :worker AND status = 'running'
            """
        ),
        {"worker": worker_id},
    )
    return result.rowcount


async def cancel_active(session: AsyncSession, repository_id: uuid.UUID) -> bool:
    """Cancel the repository's queued/running job. ``True`` if there was one."""
    result = await session.execute(
        text(
            """
            UPDATE indexing_jobs
            SET status = 'cancelled', finished_at = now(), updated_at = now(), lease_expires_at = NULL,
                error = 'Cancelled by request.'
            WHERE repository_id = :repo AND status IN ('queued', 'running')
            """
        ),
        {"repo": repository_id},
    )
    return result.rowcount > 0


async def seconds_until_next_work(session: AsyncSession) -> Optional[float]:
    """Seconds until a job becomes claimable (may be <= 0 if already due), or ``None`` if nothing is pending."""
    value = (await session.execute(_NEXT_DELAY_SQL)).scalar_one_or_none()
    return float(value) if value is not None else None
