"""Indexing-job ORM model — the Postgres-backed work queue (ADR-028).

One row per request to (re)index a repository. Workers claim rows with
``FOR UPDATE SKIP LOCKED`` and hold a time-limited *lease* that they renew
by heartbeat; a job whose lease lapses (the host died or was recycled) can
be claimed again. The partial unique index allows at most one *active*
(queued or running) job per repository, which is what makes a duplicate
trigger structurally impossible in this mode.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

VALID_JOB_KINDS = ("full_index", "knowledge_reindex")
VALID_JOB_STATUSES = ("queued", "running", "succeeded", "failed", "cancelled")
ACTIVE_JOB_STATUSES = ("queued", "running")

_kind_check_sql = "kind IN (" + ", ".join(f"'{value}'" for value in VALID_JOB_KINDS) + ")"
_status_check_sql = "status IN (" + ", ".join(f"'{value}'" for value in VALID_JOB_STATUSES) + ")"


class IndexingJob(Base, TimestampMixin):
    """A queued, running, or finished request to index one repository."""

    __tablename__ = "indexing_jobs"
    __table_args__ = (
        CheckConstraint(_kind_check_sql, name="kind"),
        CheckConstraint(_status_check_sql, name="status"),
        # At most one active job per repository.
        Index(
            "uq_indexing_jobs_one_active_per_repository",
            "repository_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        # Serves the claim query.
        Index("ix_indexing_jobs_claim", "status", "available_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    # Not claimable before this time: how a retry waits out its backoff without anyone polling.
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    claimed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Clone-size caps for guests (ADR-027); only consulted when the job has to clone first.
    max_files: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
