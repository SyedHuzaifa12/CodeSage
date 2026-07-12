"""RepositoryWorkspace ORM model — per-repository file-scan state and statistics.

Tracks workspace-processing progress (file walk + metadata collection),
deliberately separate from ``Repository.status`` (clone lifecycle) and
from the future real indexing pipeline's own state (Sprint 2+). One row
per repository (1:1).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, BigInteger, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository

VALID_WORKSPACE_STATUSES = ("pending", "scanning", "ready", "failed")

_status_check_sql = "status IN (" + ", ".join(f"'{value}'" for value in VALID_WORKSPACE_STATUSES) + ")"


class RepositoryWorkspace(Base, TimestampMixin):
    """Workspace scan state and statistics for a single repository (1:1)."""

    __tablename__ = "repository_workspace"
    __table_args__ = (
        # Bare token "status", not "ck_repository_workspace_status" — the
        # naming convention in models/base.py prepends "ck_<table>_" itself.
        CheckConstraint(_status_check_sql, name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    progress: Mapped[int] = mapped_column(nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    total_files: Mapped[int] = mapped_column(nullable=False, default=0)
    supported_files: Mapped[int] = mapped_column(nullable=False, default=0)
    ignored_files: Mapped[int] = mapped_column(nullable=False, default=0)
    folder_count: Mapped[int] = mapped_column(nullable=False, default=0)
    repository_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    language_distribution: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    repository: Mapped["Repository"] = relationship(back_populates="workspace")
