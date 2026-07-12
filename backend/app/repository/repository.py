"""Repository data-access layer — SQLAlchemy queries only, no business logic.

All queries use the injected ``AsyncSession``; no raw SQL anywhere.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
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


async def get_by_github_url(session: AsyncSession, github_url: str) -> Optional[Repository]:
    """Fetch a repository by its source GitHub URL.

    Args:
        session: The active database session.
        github_url: The URL to match.

    Returns:
        The matching repository, or ``None`` if not found.
    """
    result = await session.execute(select(Repository).where(Repository.github_url == github_url))
    return result.scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[Repository]:
    """Fetch every repository, most recently created first.

    Args:
        session: The active database session.

    Returns:
        All repository rows.
    """
    result = await session.execute(select(Repository).order_by(Repository.created_at.desc()))
    return list(result.scalars().all())


async def delete(session: AsyncSession, repository: Repository) -> None:
    """Remove a repository row, cascading to all child tables.

    Args:
        session: The active database session.
        repository: The ORM instance to delete.
    """
    await session.delete(repository)
    await session.flush()
