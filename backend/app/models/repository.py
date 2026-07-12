"""Repository ORM model.

Represents a single imported/indexed repository. Its own indexing
lifecycle (status, progress, last error) is tracked directly on this
table per CLAUDE.md §6 — indexing runs as a FastAPI ``BackgroundTask``,
not a separate job-queue system, so there is no dedicated jobs table.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.conversation import Conversation
    from app.models.file import File
    from app.models.relationship import Relationship
    from app.models.report import Report

VALID_REPOSITORY_STATUSES = ("pending", "cloning", "ready", "failed", "deleted")

_status_check_sql = "status IN (" + ", ".join(f"'{value}'" for value in VALID_REPOSITORY_STATUSES) + ")"


class Repository(Base, TimestampMixin):
    """A single repository CodeSage has imported and (optionally) indexed."""

    __tablename__ = "repositories"
    __table_args__ = (
        # Passed as a bare token, not "ck_repositories_status" — the naming
        # convention in models/base.py prepends "ck_<table>_" itself, so a
        # pre-qualified name here would double up (ck_repositories_ck_repositories_status).
        CheckConstraint(_status_check_sql, name="status"),
        Index("ix_repositories_github_url", "github_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    github_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    local_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    indexing_progress: Mapped[int] = mapped_column(nullable=False, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    files: Mapped[list["File"]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    knowledge_relationships: Mapped[list["Relationship"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
    reports: Mapped[list["Report"]] = relationship(back_populates="repository", cascade="all, delete-orphan")
    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="repository", cascade="all, delete-orphan"
    )
