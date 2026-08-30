"""Knowledge data-access layer — SQLAlchemy queries only, no business logic."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_index_state import KnowledgeIndexState


async def get_index_state(session: AsyncSession, repository_id: uuid.UUID) -> Optional[KnowledgeIndexState]:
    """Fetch a repository's knowledge-indexing state, if it exists.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.

    Returns:
        The matching state row, or ``None`` if indexing has never run.
    """
    result = await session.execute(
        select(KnowledgeIndexState).where(KnowledgeIndexState.repository_id == repository_id)
    )
    return result.scalar_one_or_none()


async def create_index_state(session: AsyncSession, state: KnowledgeIndexState) -> KnowledgeIndexState:
    """Persist a new knowledge-indexing state row.

    Args:
        session: The active database session.
        state: The unsaved ORM instance to insert.

    Returns:
        The same instance, refreshed with database-generated defaults.
    """
    session.add(state)
    await session.flush()
    await session.refresh(state)
    return state


async def save_index_state(session: AsyncSession, state: KnowledgeIndexState) -> KnowledgeIndexState:
    """Flush and refresh a tracked state instance after in-place edits.

    Args:
        session: The active database session.
        state: An already-tracked ORM instance with pending changes.

    Returns:
        The same instance, refreshed from the database.
    """
    await session.flush()
    await session.refresh(state)
    return state


async def is_file_up_to_date(
    session: AsyncSession, file_id: uuid.UUID, file_content_hash: str, embedding_model_version: str
) -> bool:
    """Check whether a file already has chunks for its current content and embedding version.

    A file with zero symbols/content that legitimately produces zero
    chunks always reports "not up to date" here (there is nothing to
    match against) — it gets cheaply re-chunked every run. Documented
    as a known, low-cost limitation rather than adding a separate
    per-file tracking table.

    Args:
        session: The active database session.
        file_id: The file to check.
        file_content_hash: The file's current ``content_hash``.
        embedding_model_version: The active embedding configuration's version string.

    Returns:
        ``True`` if at least one existing chunk matches both values.
    """
    query = select(
        exists().where(
            KnowledgeChunk.file_id == file_id,
            KnowledgeChunk.file_content_hash == file_content_hash,
            KnowledgeChunk.embedding_model_version == embedding_model_version,
        )
    )
    result = await session.execute(query)
    return bool(result.scalar())


async def get_chunk_ids_for_file(session: AsyncSession, file_id: uuid.UUID) -> list[uuid.UUID]:
    """Fetch every existing chunk id for a file (needed before deleting its Qdrant points).

    Args:
        session: The active database session.
        file_id: The owning file's UUID.

    Returns:
        The file's current chunk ids.
    """
    result = await session.execute(select(KnowledgeChunk.id).where(KnowledgeChunk.file_id == file_id))
    return list(result.scalars().all())


async def delete_chunks_for_file(session: AsyncSession, file_id: uuid.UUID) -> None:
    """Delete every chunk row for a file (Postgres side only — Qdrant is a separate call).

    Args:
        session: The active database session.
        file_id: The owning file's UUID.
    """
    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.file_id == file_id))
    await session.flush()


async def insert_chunks(session: AsyncSession, chunks: list[KnowledgeChunk]) -> None:
    """Persist a freshly built batch of chunk rows.

    Args:
        session: The active database session.
        chunks: New chunk rows to insert (no-op if empty).
    """
    if not chunks:
        return
    session.add_all(chunks)
    await session.flush()


async def list_chunks(
    session: AsyncSession,
    repository_id: uuid.UUID,
    file_id: Optional[uuid.UUID] = None,
    chunk_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[KnowledgeChunk]:
    """Fetch a page of chunk metadata for a repository, for inspection/validation.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        file_id: Optional filter to one file.
        chunk_type: Optional filter to one chunk type.
        limit: Maximum rows to return.
        offset: Rows to skip (pagination).

    Returns:
        Matching chunk rows, ordered by file then position within file.
    """
    query = select(KnowledgeChunk).where(KnowledgeChunk.repository_id == repository_id)
    if file_id is not None:
        query = query.where(KnowledgeChunk.file_id == file_id)
    if chunk_type is not None:
        query = query.where(KnowledgeChunk.chunk_type == chunk_type)
    query = query.order_by(KnowledgeChunk.file_id, KnowledgeChunk.chunk_index).limit(limit).offset(offset)
    result = await session.execute(query)
    return list(result.scalars().all())


async def count_chunks(session: AsyncSession, repository_id: uuid.UUID) -> int:
    """Count every chunk for a repository.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.

    Returns:
        Total chunk count.
    """
    result = await session.execute(
        select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.repository_id == repository_id)
    )
    return int(result.scalar_one())
