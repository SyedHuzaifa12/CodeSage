"""Lexical/keyword retrieval — PostgreSQL trigram search over symbols and file paths.

Deliberately scoped to *metadata* the current architecture already
indexes (symbol names/qualified names, file paths) rather than full
source-code text, which isn't persisted anywhere queryable (Knowledge
chunks store only line ranges + embeddings, never raw text in
Postgres — see Sprint 3). This is the documented, intentional lexical
scope for this sprint, not an oversight.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval.candidates import Candidate, dedup_key_for
from app.retrieval.repository import search_files_by_token, search_symbols_by_token
from app.retrieval.utils import QueryAnalysis

logger = logging.getLogger("codesage.retrieval.lexical")


async def get_lexical_candidates(
    *, session: AsyncSession, repository_id: uuid.UUID, analysis: QueryAnalysis, limit: int, min_similarity: float,
) -> list[Candidate]:
    """Match a query's identifier-like tokens against symbol and file names.

    Runs one bounded query per token (already capped by
    ``QueryAnalysis.identifier_tokens``'s own limit) rather than a
    single query over the whole sentence — an exact identifier like
    ``getUserById`` needs to match even when it's one word inside a
    much longer natural-language question.

    Args:
        session: The active database session.
        repository_id: The repository to search within.
        analysis: The parsed query (see ``retrieval/utils.py``).
        limit: Maximum candidates *per token* — the caller bounds the
            total via deduplication and the top-K cutoff, not this call.
        min_similarity: Trigram similarity floor for a non-exact match.

    Returns:
        Candidates with a ``"lexical"`` source score, empty if the
        query had no usable identifier tokens.
    """
    candidates: list[Candidate] = []

    for token in analysis.identifier_tokens:
        symbol_rows = await search_symbols_by_token(session, repository_id, token, limit, min_similarity)
        for symbol, file_path, score in symbol_rows:
            candidates.append(
                Candidate(
                    dedup_key=dedup_key_for(chunk_id=None, file_id=symbol.file_id, symbol_id=symbol.id),
                    repository_id=repository_id,
                    file_id=symbol.file_id,
                    file_path=file_path,
                    symbol_id=symbol.id,
                    symbol_name=symbol.name,
                    qualified_name=symbol.qualified_name,
                    symbol_type=symbol.symbol_type,
                    start_line=symbol.start_line,
                    end_line=symbol.end_line,
                    source_scores={"lexical": score},
                    reasons=[f"symbol name matches '{token}' (similarity {score:.2f})"],
                )
            )

        file_rows = await search_files_by_token(session, repository_id, token, limit, min_similarity)
        for file_row, score in file_rows:
            candidates.append(
                Candidate(
                    dedup_key=dedup_key_for(chunk_id=None, file_id=file_row.id, symbol_id=None),
                    repository_id=repository_id,
                    file_id=file_row.id,
                    file_path=file_row.path,
                    language=file_row.language,
                    source_scores={"lexical": score},
                    reasons=[f"file path matches '{token}' (similarity {score:.2f})"],
                )
            )

    return candidates
