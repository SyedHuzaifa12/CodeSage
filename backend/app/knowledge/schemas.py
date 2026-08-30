"""Knowledge request/response DTOs — validation only, no business logic."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class KnowledgeIndexStateResponse(BaseModel):
    """Serialized knowledge-indexing status and latency/cache metrics for a repository."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    repository_id: uuid.UUID
    status: str
    progress: int
    error_message: Optional[str]
    embedding_model_version: Optional[str]
    total_files_considered: int
    total_files_skipped_unchanged: int
    total_files_failed: int
    total_chunks: int
    total_chunks_from_cache: int
    total_chunks_embedded_fresh: int
    last_indexed_at: Optional[datetime]
    chunking_ms: Optional[int]
    embedding_ms: Optional[int]
    upsert_ms: Optional[int]
    total_ms: Optional[int]
    created_at: datetime
    updated_at: datetime


class ChunkResponse(BaseModel):
    """A single chunk's metadata, for inspection — never the full text over the wire."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    file_id: uuid.UUID
    symbol_id: Optional[uuid.UUID]
    chunk_index: int
    chunk_type: str
    start_line: int
    end_line: int
    char_count: int
    language: Optional[str]
    content_hash: str
    embedding_model_version: str


class ChunkListData(BaseModel):
    """Payload shape for ``GET /repositories/{id}/chunks``."""

    repository_id: uuid.UUID
    chunks: list[ChunkResponse]
    limit: int
    offset: int


class KnowledgeReindexResponse(BaseModel):
    """Payload shape for ``POST /repositories/{id}/knowledge/reindex``."""

    repository_id: uuid.UUID
    message: str
