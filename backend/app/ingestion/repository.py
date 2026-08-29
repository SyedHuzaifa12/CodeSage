"""Ingestion data-access layer — SQLAlchemy queries only, no business logic.

All queries use the injected ``AsyncSession``; no raw SQL anywhere.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.parsers.base import ExtractedSymbol
from app.models.file import File
from app.models.relationship import Relationship
from app.models.repository_intelligence import RepositoryIntelligence
from app.models.repository_workspace import RepositoryWorkspace
from app.models.symbol import Symbol


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


async def save_file(session: AsyncSession, file_row: File) -> File:
    """Flush and refresh a tracked file instance after in-place edits.

    Args:
        session: The active database session.
        file_row: An already-tracked ORM instance with pending changes
            (used to persist a computed ``content_hash``).

    Returns:
        The same instance, refreshed from the database.
    """
    await session.flush()
    await session.refresh(file_row)
    return file_row


async def replace_symbols_for_file(
    session: AsyncSession, file_id: uuid.UUID, extracted_symbols: list[ExtractedSymbol]
) -> list[Symbol]:
    """Replace every symbol row for a single file with a freshly parsed set.

    Two-phase insert: symbols are inserted first (to obtain database
    IDs), then ``parent_symbol_id`` is resolved from each extracted
    symbol's ``parent_qualified_name`` against the just-inserted rows —
    parent/child nesting only ever occurs within one file's own AST, so
    no cross-file lookup is needed.

    Args:
        session: The active database session.
        file_id: The owning file's UUID.
        extracted_symbols: Freshly parsed symbols for this file (may be empty).

    Returns:
        The persisted :class:`Symbol` rows.
    """
    await session.execute(delete(Symbol).where(Symbol.file_id == file_id))
    if not extracted_symbols:
        await session.flush()
        return []

    rows = [
        Symbol(
            file_id=file_id,
            name=extracted.name,
            qualified_name=extracted.qualified_name,
            symbol_type=extracted.symbol_type,
            visibility=extracted.visibility,
            start_line=extracted.start_line,
            end_line=extracted.end_line,
            signature=extracted.signature,
        )
        for extracted in extracted_symbols
    ]
    session.add_all(rows)
    await session.flush()

    qualified_name_to_id = {row.qualified_name: row.id for row in rows}
    for extracted, row in zip(extracted_symbols, rows):
        if extracted.parent_qualified_name and extracted.parent_qualified_name in qualified_name_to_id:
            row.parent_symbol_id = qualified_name_to_id[extracted.parent_qualified_name]
    await session.flush()
    return rows


async def replace_relationships(
    session: AsyncSession, repository_id: uuid.UUID, relationships: list[tuple[str, str, str]]
) -> None:
    """Replace every relationship row for a repository with a freshly parsed set.

    Relationships are not file-scoped (CLAUDE.md §8's Knowledge Graph is
    repository-wide), so a full re-index always rebuilds the complete
    set rather than diffing per file.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        relationships: Deduplicated ``(source_symbol, target_symbol,
            relationship_type)`` tuples collected across every parsed file.
    """
    await session.execute(delete(Relationship).where(Relationship.repository_id == repository_id))
    if relationships:
        session.add_all(
            Relationship(
                repository_id=repository_id, source_symbol=source, target_symbol=target, relationship_type=rel_type
            )
            for source, target, rel_type in relationships
        )
    await session.flush()


async def replace_relationships_of_type(
    session: AsyncSession, repository_id: uuid.UUID, relationship_type: str, relationships: list[tuple[str, str]]
) -> None:
    """Replace only one relationship_type's rows for a repository, leaving others untouched.

    Used for the Call Graph (Sprint 2B), which adds a new
    ``relationship_type="calls"`` on top of Sprint 2A's already-persisted
    extends/implements/belongs_to/imports edges — those are left exactly
    as parsing produced them; only ``calls`` rows are replaced on re-analysis.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        relationship_type: The single relationship type being replaced (e.g. ``"calls"``).
        relationships: Deduplicated ``(source_symbol, target_symbol)`` pairs.
    """
    await session.execute(
        delete(Relationship).where(
            Relationship.repository_id == repository_id, Relationship.relationship_type == relationship_type
        )
    )
    if relationships:
        session.add_all(
            Relationship(
                repository_id=repository_id, source_symbol=source, target_symbol=target, relationship_type=relationship_type
            )
            for source, target in relationships
        )
    await session.flush()


async def list_symbols_for_repository(session: AsyncSession, repository_id: uuid.UUID) -> list[Symbol]:
    """Fetch every symbol across every file of a repository.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.

    Returns:
        All symbol rows for the repository, joined through their file.
    """
    result = await session.execute(
        select(Symbol).join(File, File.id == Symbol.file_id).where(File.repository_id == repository_id)
    )
    return list(result.scalars().all())


async def list_relationships(
    session: AsyncSession, repository_id: uuid.UUID, relationship_type: Optional[str] = None
) -> list[Relationship]:
    """Fetch relationships for a repository, optionally filtered by type.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        relationship_type: If given, only relationships of this type are returned.

    Returns:
        Matching relationship rows.
    """
    query = select(Relationship).where(Relationship.repository_id == repository_id)
    if relationship_type is not None:
        query = query.where(Relationship.relationship_type == relationship_type)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_intelligence(session: AsyncSession, repository_id: uuid.UUID) -> Optional[RepositoryIntelligence]:
    """Fetch a repository's intelligence row, if it exists.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.

    Returns:
        The matching intelligence row, or ``None`` if never analyzed.
    """
    result = await session.execute(
        select(RepositoryIntelligence).where(RepositoryIntelligence.repository_id == repository_id)
    )
    return result.scalar_one_or_none()


async def create_intelligence(session: AsyncSession, intelligence: RepositoryIntelligence) -> RepositoryIntelligence:
    """Persist a new intelligence row.

    Args:
        session: The active database session.
        intelligence: The unsaved ORM instance to insert.

    Returns:
        The same instance, refreshed with database-generated defaults.
    """
    session.add(intelligence)
    await session.flush()
    await session.refresh(intelligence)
    return intelligence


async def save_intelligence(session: AsyncSession, intelligence: RepositoryIntelligence) -> RepositoryIntelligence:
    """Flush and refresh a tracked intelligence instance after in-place edits.

    Args:
        session: The active database session.
        intelligence: An already-tracked ORM instance with pending changes.

    Returns:
        The same instance, refreshed from the database.
    """
    await session.flush()
    await session.refresh(intelligence)
    return intelligence
