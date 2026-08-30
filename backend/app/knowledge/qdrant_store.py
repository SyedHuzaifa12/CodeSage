"""Qdrant ``repository_chunks`` collection — schema bootstrap + point I/O.

Single collection for the whole project (CLAUDE.md §9: "do not create
additional collections without approval"). Every point id is the same
UUID as its ``KnowledgeChunk`` Postgres row, so the two stores are
always addressable by one id with no separate mapping table.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from qdrant_client import AsyncQdrantClient, models

from app.core.config import get_settings

logger = logging.getLogger("codesage.knowledge.qdrant_store")

COLLECTION_NAME = "repository_chunks"


async def ensure_collection(client: AsyncQdrantClient) -> None:
    """Create the ``repository_chunks`` collection and its payload indexes if absent.

    Idempotent — safe to call on every application startup. Vector size
    is read from the active embedding configuration, so a model swap
    that changes dimensionality is caught here with a clear error
    rather than a confusing Qdrant dimension-mismatch failure on the
    first upsert.

    Args:
        client: The shared async Qdrant client.

    Raises:
        ValueError: If the collection already exists with a different
            vector size than the currently configured embedding model.
    """
    settings = get_settings()
    dimension = settings.llm.embedding_dimension

    existing = {c.name for c in (await client.get_collections()).collections}
    if COLLECTION_NAME in existing:
        info = await client.get_collection(COLLECTION_NAME)
        current_size = info.config.params.vectors.size
        if current_size != dimension:
            raise ValueError(
                f"Qdrant collection '{COLLECTION_NAME}' has vector size {current_size}, "
                f"but the configured embedding model expects {dimension}. "
                "This requires an explicit migration (new collection + full re-index), not an automatic one."
            )
        return

    await client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
    )
    # Every future Retrieval query filters by repository_id first (never
    # searches across repositories), so this is the one payload index
    # that matters for query latency; the others are cheap keyword
    # indexes to support Sprint 4's finer-grained filtering.
    for field_name in ("repository_id", "file_id", "chunk_type", "language"):
        await client.create_payload_index(
            collection_name=COLLECTION_NAME, field_name=field_name, field_schema=models.PayloadSchemaType.KEYWORD
        )
    logger.info("Created Qdrant collection '%s' (dimension=%d)", COLLECTION_NAME, dimension)


def build_point(
    chunk_id: uuid.UUID,
    vector: list[float],
    *,
    repository_id: uuid.UUID,
    file_id: uuid.UUID,
    symbol_id: Optional[uuid.UUID],
    file_path: str,
    language: Optional[str],
    chunk_type: str,
    start_line: int,
    end_line: int,
    content_hash: str,
    embedding_model_version: str,
) -> models.PointStruct:
    """Build one Qdrant point from a chunk's vector and metadata.

    Args:
        chunk_id: The chunk's UUID (shared with its Postgres row).
        vector: The chunk's embedding.
        repository_id: Owning repository (primary retrieval filter).
        file_id: Owning file.
        symbol_id: Owning symbol, if this chunk represents one.
        file_path: Repository-relative file path (for display without a join).
        language: The file's detected language.
        chunk_type: ``symbol`` / ``symbol_split`` / ``fallback``.
        start_line: 1-indexed start line.
        end_line: 1-indexed end line.
        content_hash: The chunk's own text hash.
        embedding_model_version: The embedding config active when this vector was computed.

    Returns:
        A point ready to upsert.
    """
    return models.PointStruct(
        id=str(chunk_id),
        vector=vector,
        payload={
            "repository_id": str(repository_id),
            "file_id": str(file_id),
            "symbol_id": str(symbol_id) if symbol_id else None,
            "file_path": file_path,
            "language": language,
            "chunk_type": chunk_type,
            "start_line": start_line,
            "end_line": end_line,
            "content_hash": content_hash,
            "embedding_model_version": embedding_model_version,
        },
    )


async def upsert_points(client: AsyncQdrantClient, points: list[models.PointStruct]) -> None:
    """Upsert a batch of points into the collection.

    Args:
        client: The shared async Qdrant client.
        points: Points to write (no-op if empty).
    """
    if not points:
        return
    await client.upsert(collection_name=COLLECTION_NAME, points=points)


async def delete_points_by_ids(client: AsyncQdrantClient, point_ids: list[uuid.UUID]) -> None:
    """Delete specific points by id (used when replacing a file's chunks).

    Args:
        client: The shared async Qdrant client.
        point_ids: Chunk ids to remove (no-op if empty).
    """
    if not point_ids:
        return
    await client.delete(collection_name=COLLECTION_NAME, points_selector=[str(pid) for pid in point_ids])


async def search_points(
    client: AsyncQdrantClient, repository_id: uuid.UUID, vector: list[float], limit: int
) -> list[models.ScoredPoint]:
    """Semantic (vector) search scoped to a single repository.

    Every call filters by ``repository_id`` — Sprint 4's retrieval
    isolation guarantee is enforced here, at the one place a cross-
    repository leak could otherwise happen, not left to callers to
    remember.

    Args:
        client: The shared async Qdrant client.
        repository_id: The repository to search within — no other
            repository's points are ever considered.
        vector: The query embedding.
        limit: Maximum points to return.

    Returns:
        Scored points, highest similarity first (Qdrant's own ordering
        for the collection's ``Cosine`` distance).
    """
    response = await client.query_points(
        collection_name=COLLECTION_NAME,
        query=vector,
        query_filter=models.Filter(
            must=[models.FieldCondition(key="repository_id", match=models.MatchValue(value=str(repository_id)))]
        ),
        limit=limit,
        with_payload=True,
    )
    return response.points


async def delete_points_by_repository(client: AsyncQdrantClient, repository_id: uuid.UUID) -> None:
    """Delete every point belonging to a repository (reset / hard delete).

    Args:
        client: The shared async Qdrant client.
        repository_id: The repository whose points should be removed.
    """
    await client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="repository_id", match=models.MatchValue(value=str(repository_id)))]
            )
        ),
    )
