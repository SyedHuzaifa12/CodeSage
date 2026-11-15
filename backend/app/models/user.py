"""User ORM model (ADR-027).

A user is either a ``guest`` (server-issued, expiring, one-repository
identity created without sign-in) or a ``user`` (a member identified by
GitHub). A guest is upgraded in place on first GitHub login, so the
same row — and every repository it owns — carries over.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

VALID_USER_KINDS = ("guest", "user")

_kind_check_sql = "kind IN (" + ", ".join(f"'{value}'" for value in VALID_USER_KINDS) + ")"


class User(Base, TimestampMixin):
    """An identity that can own repositories."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(_kind_check_sql, name="kind"),
        Index("ix_users_guest_expires_at", "guest_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="guest")
    github_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, unique=True)
    github_login: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set only for guests; cleared when a guest is upgraded to a member.
    guest_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
