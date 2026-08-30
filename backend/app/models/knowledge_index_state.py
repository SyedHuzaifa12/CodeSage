"""KnowledgeIndexState ORM model — per-repository knowledge indexing status.

Sprint 3 (Knowledge). 1:1 with ``repositories``, mirroring the same
pattern already used by ``RepositoryWorkspace`` (Sprint 1B) and
``RepositoryIntelligence`` (Sprint 2B): a small status/progress row
tracking one background pipeline stage, so ``GET`` endpoints and
DevTools never need to scan the (potentially large) chunks table just
to answer "is indexing done yet".
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository

VALID_KNOWLEDGE_STATUSES = ("pending", "indexing", "ready", "failed")

_status_check_sql = "status IN (" + ", ".join(f"'{value}'" for value in VALID_KNOWLEDGE_STATUSES) + ")"


class KnowledgeIndexState(Base, TimestampMixin):
    """Tracks the knowledge-indexing pipeline's status for one repository."""

    __tablename__ = "knowledge_index_state"
    __table_args__ = (CheckConstraint(_status_check_sql, name="status"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    embedding_model_version: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    total_files_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_files_skipped_unchanged: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_files_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_chunks_from_cache: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_chunks_embedded_fresh: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    chunking_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    embedding_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    upsert_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    repository: Mapped["Repository"] = relationship(back_populates="knowledge_index_state")
