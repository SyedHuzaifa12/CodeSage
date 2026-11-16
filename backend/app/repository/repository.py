"""Repository data-access layer — SQLAlchemy queries only, no business logic.

All queries use the injected ``AsyncSession``; no raw SQL anywhere.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.repository import Repository


async def create(session: AsyncSession, repository: Repository) -> Repository:
    """Persist a new repository row.

    Args:
        session: The active database session.
        repository: The unsaved ORM instance to insert.

    Returns:
        The same instance, refreshed with database-generated defaults
        (``id``, ``created_at``, ``updated_at``).
    """
    session.add(repository)
    await session.flush()
    await session.refresh(repository)
    return repository


async def save(session: AsyncSession, repository: Repository) -> Repository:
    """Flush and refresh a tracked repository instance after in-place edits.

    Args:
        session: The active database session.
        repository: An already-tracked ORM instance with pending changes.

    Returns:
        The same instance, refreshed from the database (e.g. ``updated_at``).
    """
    await session.flush()
    await session.refresh(repository)
    return repository


async def get_by_id(session: AsyncSession, repository_id: uuid.UUID) -> Optional[Repository]:
    """Fetch a single repository by primary key.

    Args:
        session: The active database session.
        repository_id: The repository's UUID primary key.

    Returns:
        The matching repository, or ``None`` if not found.
    """
    return await session.get(Repository, repository_id)


async def get_by_github_url(session: AsyncSession, github_url: str, owner_id: uuid.UUID) -> Optional[Repository]:
    """Fetch one of an owner's non-failed repositories by its source GitHub URL.

    Scoped to the owner so one user's imports are never visible to (or
    block) another's. Failed rows are ignored so a failed clone can be retried.

    Args:
        session: The active database session.
        github_url: The URL to match.
        owner_id: The user whose repositories to search.

    Returns:
        The matching repository, or ``None`` if not found.
    """
    result = await session.execute(
        select(Repository)
        .where(
            Repository.github_url == github_url,
            Repository.owner_id == owner_id,
            Repository.status != "failed",
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_visible(session: AsyncSession, owner_id: uuid.UUID) -> list[Repository]:
    """Fetch the repositories a user may see — their own plus every demo — newest first.

    Args:
        session: The active database session.
        owner_id: The viewing user.

    Returns:
        The visible repository rows.
    """
    result = await session.execute(
        select(Repository)
        .where(or_(Repository.owner_id == owner_id, Repository.is_demo.is_(True)))
        .order_by(Repository.created_at.desc())
    )
    return list(result.scalars().all())


async def delete(session: AsyncSession, repository: Repository) -> None:
    """Remove a repository row, cascading to all child tables.

    Args:
        session: The active database session.
        repository: The ORM instance to delete.
    """
    await session.delete(repository)
    await session.flush()
