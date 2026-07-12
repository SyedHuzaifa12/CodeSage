"""Conversation ORM model — persistent chat history for a repository.

Persistent storage only (CLAUDE.md §7): transient/session conversation
state (last-N turns, in-flight retrieval cache) lives in Redis, not here.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository


class Conversation(Base, TimestampMixin):
    """A single persisted question/answer turn for a repository."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    repository: Mapped["Repository"] = relationship(back_populates="conversations")
