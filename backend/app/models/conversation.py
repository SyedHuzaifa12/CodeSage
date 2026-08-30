"""Conversation ORM model — persistent chat history for a repository.

Persistent storage only (CLAUDE.md §7): transient/session conversation
state (last-N turns, in-flight retrieval cache) lives in Redis, not here.

``intent``/``verification_status``/``total_latency_ms`` were added in
Sprint 5 (AI Engine) — additive, nullable columns on this
already-existing-but-previously-unused table (see migration
``add_conversation_metadata``); a row written before Sprint 5 simply
never existed, since nothing wrote to this table until now.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository

VALID_VERIFICATION_STATUSES = ("supported", "partially_supported", "insufficient_evidence", "contradicted")

_verification_status_check_sql = (
    "verification_status IN (" + ", ".join(f"'{value}'" for value in VALID_VERIFICATION_STATUSES) + ")"
)


class Conversation(Base, TimestampMixin):
    """A single persisted question/answer turn for a repository."""

    __tablename__ = "conversations"
    __table_args__ = (
        # Bare token "verification_status", not "ck_conversations_verification_status" —
        # see the matching note on Repository.status for why a
        # pre-qualified name would double up under the naming
        # convention in models/base.py.
        CheckConstraint(_verification_status_check_sql, name="verification_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    verification_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    total_latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    repository: Mapped["Repository"] = relationship(back_populates="conversations")
