"""Reports data-access layer — SQLAlchemy queries only, no business logic.

Reports are append-only (see ``models/report.py``'s docstring and
ADR-021): there is no ``update``/``save`` here that mutates an existing
row's content — only ``create`` (one new row per generation attempt)
and read queries. ``get_latest``/``list_for_repository`` are the only
way "the current report" is derived, always by ``created_at`` recency.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.report import Report


async def create(session: AsyncSession, report: Report) -> Report:
    """Persist a new report row.

    Args:
        session: The active database session.
        report: The unsaved ORM instance to insert.

    Returns:
        The same instance, refreshed with database-generated defaults.
    """
    session.add(report)
    await session.flush()
    await session.refresh(report)
    return report


async def get_by_id(session: AsyncSession, report_id: uuid.UUID) -> Optional[Report]:
    """Fetch a single report by primary key.

    Args:
        session: The active database session.
        report_id: The report's UUID primary key.

    Returns:
        The matching report, or ``None`` if not found.
    """
    return await session.get(Report, report_id)


async def get_latest(
    session: AsyncSession, repository_id: uuid.UUID, report_type: str, *, status: Optional[str] = None
) -> Optional[Report]:
    """Fetch the most recently generated report row for one repository/type.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        report_type: The internal ``Report.report_type`` value.
        status: If given, restrict to rows in this status (e.g. ``"ready"``
            for "the latest report a client can actually be served" vs.
            ``None`` for "the latest row of any status", used by
            regeneration logic to detect an in-flight/failed attempt).

    Returns:
        The newest matching row, or ``None`` if none exists.
    """
    query = select(Report).where(Report.repository_id == repository_id, Report.report_type == report_type)
    if status is not None:
        query = query.where(Report.status == status)
    query = query.order_by(Report.created_at.desc()).limit(1)
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def list_for_repository(
    session: AsyncSession, repository_id: uuid.UUID, *, report_type: Optional[str] = None
) -> list[Report]:
    """Fetch every report row for a repository, newest first.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        report_type: If given, restrict to one report type.

    Returns:
        Matching rows, most recently created first. Callers wanting
        "one row per type" (the ``latest_only=true`` API default)
        de-duplicate this list themselves, keeping the first occurrence
        of each ``report_type`` — simpler and easier to test than a
        window-function query, and reports-per-repository is a small,
        bounded number.
    """
    query = select(Report).where(Report.repository_id == repository_id)
    if report_type is not None:
        query = query.where(Report.report_type == report_type)
    query = query.order_by(Report.created_at.desc())
    result = await session.execute(query)
    return list(result.scalars().all())
