"""Enqueue and cancel helpers used by the API-side services (ADR-028).

Thin on purpose: the services keep their own validation and status logic and
only hand the actual "put it on the queue" step to this module, so the
Celery path stays exactly as it was and the two backends differ in one place.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.indexing import repository as jobs
from app.models.indexing_job import IndexingJob


async def enqueue_job(
    session: AsyncSession,
    repository_id: uuid.UUID,
    kind: str,
    *,
    max_files: Optional[int] = None,
    max_bytes: Optional[int] = None,
    settings: Optional[Settings] = None,
) -> IndexingJob:
    """Queue a job for the repository. The caller commits, then wakes the indexer.

    Raises:
        IndexingAlreadyInProgressError: If the repository already has an active job.
    """
    settings = settings or get_settings()
    return await jobs.enqueue(
        session, repository_id, kind,
        max_attempts=settings.indexing.indexing_max_attempts, max_files=max_files, max_bytes=max_bytes,
    )


async def cancel_job(session: AsyncSession, repository_id: uuid.UUID) -> bool:
    """Cancel the repository's active job. A running one stops at its next stage boundary."""
    return await jobs.cancel_active(session, repository_id)
