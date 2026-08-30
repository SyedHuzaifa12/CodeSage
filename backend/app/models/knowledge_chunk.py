"""KnowledgeChunk ORM model — a single embedded, retrievable slice of a file.

Sprint 3 (Knowledge). One row per chunk of source text that has been
embedded into Qdrant. ``id`` is reused verbatim as the Qdrant point id —
a chunk's Postgres row and its Qdrant vector are always the same UUID,
so no separate mapping table is needed to keep the two stores in sync.

``file_content_hash`` and ``embedding_model_version`` together make
incremental re-indexing possible: a file whose current
``File.content_hash`` and the active ``LLMSettings.embedding_version``
both still match an existing chunk's stored values needs no rework at
all (see ``knowledge/service.py``).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.file import File
    from app.models.repository import Repository
    from app.models.symbol import Symbol

VALID_CHUNK_TYPES = ("symbol", "symbol_split", "fallback")

_chunk_type_check_sql = "chunk_type IN (" + ", ".join(f"'{value}'" for value in VALID_CHUNK_TYPES) + ")"


class KnowledgeChunk(Base, TimestampMixin):
    """A single chunk of source text, embedded and stored in Qdrant."""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        # Bare token "chunk_type", not "ck_knowledge_chunks_chunk_type" —
        # see the matching note on Repository.status for why a
        # pre-qualified name would double up under the naming
        # convention in models/base.py.
        CheckConstraint(_chunk_type_check_sql, name="chunk_type"),
        UniqueConstraint("file_id", "chunk_index", name="uq_knowledge_chunks_file_chunk_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    symbol_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True, index=True
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(16), nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model_version: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    repository: Mapped["Repository"] = relationship(back_populates="knowledge_chunks")
    file: Mapped["File"] = relationship(back_populates="knowledge_chunks")
    symbol: Mapped[Optional["Symbol"]] = relationship()
