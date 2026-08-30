"""Knowledge REST API — routes only, no business logic (CLAUDE.md §10).

Nested under ``/repositories/{repository_id}/...`` like the Ingestion
module's routes, since these are actions on a repository resource.
Minimal by design (per Sprint 3 scope): enough to inspect/validate
indexing state and chunk metadata, and to manually trigger a
re-index — Sprint 4 (Retrieval) is what actually queries these chunks
for search.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.knowledge import repository as knowledge_db
from app.knowledge.exceptions import RepositoryNotIndexedError
from app.knowledge.pipeline import run_knowledge_indexing_pipeline
from app.knowledge.schemas import (
    ChunkListData,
    ChunkResponse,
    KnowledgeIndexStateResponse,
    KnowledgeReindexResponse,
)
from app.repository import repository as repository_db
from app.repository.exceptions import RepositoryNotFoundError
from app.schemas.envelope import SuccessResponse

router = APIRouter(prefix="/repositories/{repository_id}/knowledge", tags=["knowledge"])


async def _require_repository(session: AsyncSession, repository_id: uuid.UUID) -> None:
    """Raise if the repository doesn't exist, so knowledge routes 404 clearly.

    Args:
        session: The active database session.
        repository_id: The repository's UUID.

    Raises:
        RepositoryNotFoundError: If no repository has that id.
    """
    if await repository_db.get_by_id(session, repository_id) is None:
        raise RepositoryNotFoundError(f"Repository '{repository_id}' was not found.")


@router.get("", response_model=SuccessResponse[KnowledgeIndexStateResponse])
async def get_knowledge_state(
    repository_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> SuccessResponse[KnowledgeIndexStateResponse]:
    """Fetch a repository's knowledge-indexing status and latency/cache metrics.

    Args:
        repository_id: The repository's UUID.
        session: Injected database session.

    Returns:
        The knowledge-index-state row.
    """
    await _require_repository(session, repository_id)
    state = await knowledge_db.get_index_state(session, repository_id)
    if state is None:
        raise RepositoryNotIndexedError(
            f"Repository '{repository_id}' has not been knowledge-indexed yet — run indexing first."
        )
    return SuccessResponse(message="Knowledge index state retrieved.", data=state)


@router.get("/chunks", response_model=SuccessResponse[ChunkListData])
async def list_chunks(
    repository_id: uuid.UUID,
    file_id: Optional[uuid.UUID] = Query(default=None),
    chunk_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> SuccessResponse[ChunkListData]:
    """Fetch a page of chunk metadata for a repository, for inspection/validation.

    Args:
        repository_id: The repository's UUID.
        file_id: Optional filter to one file.
        chunk_type: Optional filter to one chunk type (``symbol``/``symbol_split``/``fallback``).
        limit: Page size.
        offset: Page offset.
        session: Injected database session.

    Returns:
        A page of chunk metadata (never the full chunk text).
    """
    await _require_repository(session, repository_id)
    chunks = await knowledge_db.list_chunks(
        session, repository_id, file_id=file_id, chunk_type=chunk_type, limit=limit, offset=offset
    )
    data = ChunkListData(
        repository_id=repository_id,
        chunks=[ChunkResponse.model_validate(chunk) for chunk in chunks],
        limit=limit,
        offset=offset,
    )
    return SuccessResponse(message="Chunks retrieved.", data=data)


@router.post("/reindex", response_model=SuccessResponse[KnowledgeReindexResponse])
async def trigger_reindex(
    repository_id: uuid.UUID, background_tasks: BackgroundTasks, session: AsyncSession = Depends(get_db)
) -> SuccessResponse[KnowledgeReindexResponse]:
    """Manually re-run knowledge indexing for a repository in the background.

    Idempotent: unchanged files are skipped via the content-hash fast
    path, so re-running this on an already-indexed repository with no
    source changes does effectively no embedding/Qdrant work.

    Args:
        repository_id: The repository's UUID.
        background_tasks: FastAPI's background-task registrar.
        session: Injected database session.

    Returns:
        An acknowledgement payload — indexing has started, not finished.
    """
    await _require_repository(session, repository_id)
    background_tasks.add_task(run_knowledge_indexing_pipeline, repository_id)
    data = KnowledgeReindexResponse(
        repository_id=repository_id,
        message="Knowledge re-indexing started in the background. Poll GET .../knowledge for progress.",
    )
    return SuccessResponse(message="Knowledge re-indexing request accepted.", data=data)
