"""Ingestion data-access layer — SQLAlchemy queries only, no business logic.

All queries use the injected ``AsyncSession``; no raw SQL anywhere.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import File
from app.models.repository_workspace import RepositoryWorkspace


async def get_workspace(session: AsyncSession, repository_id: uuid.UUID) -> Optional[RepositoryWorkspace]:
    """Fetch a repository's workspace row, if it exists.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.

    Returns:
        The matching workspace, or ``None`` if no scan has ever run.
    """
    result = await session.execute(
        select(RepositoryWorkspace).where(RepositoryWorkspace.repository_id == repository_id)
    )
    return result.scalar_one_or_none()


async def create_workspace(session: AsyncSession, workspace: RepositoryWorkspace) -> RepositoryWorkspace:
    """Persist a new workspace row.

    Args:
        session: The active database session.
        workspace: The unsaved ORM instance to insert.

    Returns:
        The same instance, refreshed with database-generated defaults.
    """
    session.add(workspace)
    await session.flush()
    await session.refresh(workspace)
    return workspace


async def save_workspace(session: AsyncSession, workspace: RepositoryWorkspace) -> RepositoryWorkspace:
    """Flush and refresh a tracked workspace instance after in-place edits.

    Args:
        session: The active database session.
        workspace: An already-tracked ORM instance with pending changes.

    Returns:
        The same instance, refreshed from the database.
    """
    await session.flush()
    await session.refresh(workspace)
    return workspace


async def replace_files(session: AsyncSession, repository_id: uuid.UUID, files: list[File]) -> None:
    """Replace every file row for a repository with a fresh set.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        files: The newly scanned file rows to insert (may be empty).
    """
    await session.execute(delete(File).where(File.repository_id == repository_id))
    if files:
        session.add_all(files)
    await session.flush()


async def list_files(session: AsyncSession, repository_id: uuid.UUID) -> list[File]:
    """Fetch every file row for a repository, ordered by path.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.

    Returns:
        All file rows for the repository, alphabetically by path.
    """
    result = await session.execute(select(File).where(File.repository_id == repository_id).order_by(File.path))
    return list(result.scalars().all())
