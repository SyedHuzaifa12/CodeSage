"""Relationship ORM model — an edge in CodeSage's lightweight Knowledge Graph.

``source_symbol``/``target_symbol`` are indexed text identifiers, not
foreign keys to ``symbols``. The Knowledge Graph spans four logical
layers (Call Graph, Import Graph, Dependency Graph, Symbol Relationships
— CLAUDE.md §8), and not every edge endpoint is a parsed ``Symbol`` row:
Import Graph edges connect files/modules, Dependency Graph edges connect
services/APIs/database tables. A strict foreign key to ``symbols.id``
would make three of the four documented layers unrepresentable, so the
identifier is a qualified string (file path, symbol name, API route,
etc.) scoped to its repository instead.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository


class Relationship(Base, TimestampMixin):
    """A single edge in a repository's Knowledge Graph."""

    __tablename__ = "relationships"
    __table_args__ = (
        Index("ix_relationships_repository_type", "repository_id", "relationship_type"),
        Index("ix_relationships_repository_source", "repository_id", "source_symbol"),
        Index("ix_relationships_repository_target", "repository_id", "target_symbol"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_symbol: Mapped[str] = mapped_column(String(512), nullable=False)
    target_symbol: Mapped[str] = mapped_column(String(512), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)

    repository: Mapped["Repository"] = relationship(back_populates="knowledge_relationships")
