"""Retrieval data-access layer — SQLAlchemy queries only, no business logic.

Every query here is deliberately its own targeted, ``LIMIT``-bounded
statement rather than a reuse of Ingestion's ``list_symbols_for_repository``/
``list_relationships`` (which return a repository's *entire* symbol or
relationship set) — loading a whole large repository's symbols into
Python just to filter in-memory is exactly the "large repository
safety" failure mode CLAUDE.md and this sprint's brief both call out.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.file import File
from app.models.relationship import Relationship
from app.models.symbol import Symbol


async def search_symbols_by_token(
    session: AsyncSession, repository_id: uuid.UUID, token: str, limit: int, min_similarity: float
) -> list[tuple[Symbol, str, float]]:
    """Lexically match one identifier-like token against symbol names/qualified names.

    Uses ``pg_trgm``'s ``similarity()`` for fuzzy/substring scoring
    (0..1), with an exact case-insensitive match forced to a perfect
    1.0 — a query for ``AuthService`` must rank an exact-named class
    above a merely similar-looking one.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID (isolation boundary).
        token: One identifier-like token extracted from the query.
        limit: Maximum rows to return.
        min_similarity: Trigram similarity floor for a non-exact match.

    Returns:
        ``(symbol, file_path, score)`` tuples, ordered by score descending.
    """
    name_similarity = func.similarity(Symbol.name, token)
    qualified_similarity = func.similarity(Symbol.qualified_name, token)
    fuzzy_score = func.greatest(name_similarity, qualified_similarity)
    score = case(
        (func.lower(Symbol.name) == token.lower(), 1.0),
        (func.lower(Symbol.qualified_name) == token.lower(), 1.0),
        else_=fuzzy_score,
    )

    stmt = (
        select(Symbol, File.path, score.label("score"))
        .join(File, File.id == Symbol.file_id)
        .where(
            File.repository_id == repository_id,
            or_(
                Symbol.name.ilike(f"%{token}%"),
                Symbol.qualified_name.ilike(f"%{token}%"),
                fuzzy_score >= min_similarity,
            ),
        )
        .order_by(score.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1], float(row[2])) for row in result.all()]


async def search_files_by_token(
    session: AsyncSession, repository_id: uuid.UUID, token: str, limit: int, min_similarity: float
) -> list[tuple[File, float]]:
    """Lexically match one token against repository-relative file paths.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        token: One identifier-like token extracted from the query.
        limit: Maximum rows to return.
        min_similarity: Trigram similarity floor for a non-exact match.

    Returns:
        ``(file, score)`` tuples, ordered by score descending.
    """
    path_similarity = func.similarity(File.path, token)
    score = case((func.lower(File.path) == token.lower(), 1.0), else_=path_similarity)

    stmt = (
        select(File, score.label("score"))
        .where(
            File.repository_id == repository_id,
            or_(File.path.ilike(f"%{token}%"), path_similarity >= min_similarity),
        )
        .order_by(score.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(row[0], float(row[1])) for row in result.all()]


async def get_symbols_by_qualified_names(
    session: AsyncSession, repository_id: uuid.UUID, qualified_names: list[str], limit: int
) -> list[tuple[Symbol, str]]:
    """Resolve relationship endpoints (qualified-name strings) back to symbol rows.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        qualified_names: Qualified names to resolve (deduplicated by the caller).
        limit: Maximum rows to return.

    Returns:
        ``(symbol, file_path)`` tuples for whichever names matched a
        real symbol — an unresolvable name (e.g. an external package)
        simply contributes no rows.
    """
    if not qualified_names:
        return []
    stmt = (
        select(Symbol, File.path)
        .join(File, File.id == Symbol.file_id)
        .where(File.repository_id == repository_id, Symbol.qualified_name.in_(qualified_names))
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [(row[0], row[1]) for row in result.all()]


async def get_relationships_touching(
    session: AsyncSession, repository_id: uuid.UUID, qualified_names: list[str], limit: int
) -> list[Relationship]:
    """Fetch relationships where any seed symbol is the source or target — one hop only.

    Deliberately not recursive: expanding transitively (callers of
    callers, etc.) is the "unrestricted graph traversal" this sprint
    explicitly excludes.

    Args:
        session: The active database session.
        repository_id: The owning repository's UUID.
        qualified_names: Seed symbols' qualified names.
        limit: Maximum rows to return.

    Returns:
        Matching relationship rows.
    """
    if not qualified_names:
        return []
    stmt = (
        select(Relationship)
        .where(
            Relationship.repository_id == repository_id,
            or_(Relationship.source_symbol.in_(qualified_names), Relationship.target_symbol.in_(qualified_names)),
        )
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_symbol_by_id(session: AsyncSession, symbol_id: uuid.UUID) -> Optional[tuple[Symbol, str]]:
    """Fetch one symbol and its owning file's path by id.

    Args:
        session: The active database session.
        symbol_id: The symbol's UUID.

    Returns:
        ``(symbol, file_path)``, or ``None`` if not found.
    """
    stmt = select(Symbol, File.path).join(File, File.id == Symbol.file_id).where(Symbol.id == symbol_id)
    result = await session.execute(stmt)
    row = result.first()
    return (row[0], row[1]) if row else None


async def get_symbols_by_ids(session: AsyncSession, symbol_ids: list[uuid.UUID]) -> dict[uuid.UUID, Symbol]:
    """Bulk-resolve symbol ids to their rows — one query, not one per candidate.

    Used to enrich semantic-search hits (Qdrant's payload carries a
    ``symbol_id`` but not the symbol's name/qualified name/type) after
    ranking, bounded to the final top-K results rather than every raw
    candidate — evidence quality for the results actually returned,
    without inflating retrieval-time DB load for the ones discarded.

    Args:
        session: The active database session.
        symbol_ids: Symbol ids to resolve (deduplicated by the caller
            not required — duplicates are harmless).

    Returns:
        Mapping of symbol id to its row, containing only ids that
        resolved to a real symbol.
    """
    if not symbol_ids:
        return {}
    stmt = select(Symbol).where(Symbol.id.in_(set(symbol_ids)))
    result = await session.execute(stmt)
    return {symbol.id: symbol for symbol in result.scalars().all()}
