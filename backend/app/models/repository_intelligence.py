"""RepositoryIntelligence ORM model — post-parsing repository-level analysis.

Deliberately separate from ``repository_workspace`` (Sprint 1B's
file-walk/scan statistics) and from ``repositories.indexing_status``
(Sprint 2A's parsing lifecycle) — this table holds the *next* stage:
statistics, dependency analysis, and a rule-based summary computed from
already-persisted symbols/relationships. One row per repository (1:1).

No AI, no embeddings, no Knowledge Graph expansion — every field here
is derived by pure aggregation/graph-algorithm over data Sprint 2A
already parsed (CLAUDE.md §6's "symbol/import extraction" continuing
into repository-level analysis).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository

VALID_INTELLIGENCE_STATUSES = ("pending", "analyzing", "ready", "failed")

_status_check_sql = "status IN (" + ", ".join(f"'{value}'" for value in VALID_INTELLIGENCE_STATUSES) + ")"


class RepositoryIntelligence(Base, TimestampMixin):
    """Repository-level statistics, dependency analysis, and summary (1:1 per repository)."""

    __tablename__ = "repository_intelligence"
    __table_args__ = (
        # Bare token "status", not "ck_repository_intelligence_status" —
        # see the matching note on Repository.status for why a
        # pre-qualified name would double up under the naming convention.
        CheckConstraint(_status_check_sql, name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Statistics (Sprint 2B item 5) ---
    total_symbols: Mapped[int] = mapped_column(nullable=False, default=0)
    total_classes: Mapped[int] = mapped_column(nullable=False, default=0)
    total_interfaces: Mapped[int] = mapped_column(nullable=False, default=0)
    total_enums: Mapped[int] = mapped_column(nullable=False, default=0)
    total_functions: Mapped[int] = mapped_column(nullable=False, default=0)
    total_methods: Mapped[int] = mapped_column(nullable=False, default=0)
    total_variables: Mapped[int] = mapped_column(nullable=False, default=0)
    total_namespaces: Mapped[int] = mapped_column(nullable=False, default=0)
    total_imports: Mapped[int] = mapped_column(nullable=False, default=0)
    total_calls: Mapped[int] = mapped_column(nullable=False, default=0)
    inheritance_count: Mapped[int] = mapped_column(nullable=False, default=0)
    dependency_count: Mapped[int] = mapped_column(nullable=False, default=0)

    # --- Dependency analysis (Sprint 2B item 4) ---
    circular_dependencies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    orphan_files: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # --- Repository summary (Sprint 2B item 6) ---
    languages: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    architecture_hints: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    entry_points: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    largest_modules: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    dependency_hotspots: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    repository: Mapped["Repository"] = relationship(back_populates="intelligence")
