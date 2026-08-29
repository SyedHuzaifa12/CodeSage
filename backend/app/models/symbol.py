"""Symbol ORM model — a function, class, method, or other extracted code symbol."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.file import File

VALID_SYMBOL_VISIBILITIES = ("public", "protected", "private", "package-private")

_visibility_check_sql = "visibility IN (" + ", ".join(f"'{value}'" for value in VALID_SYMBOL_VISIBILITIES) + ")"


class Symbol(Base, TimestampMixin):
    """A function, class, method, interface, or other symbol extracted from a file.

    ``symbol_type`` is deliberately left as an open, unconstrained string
    (no ``CHECK``) — CLAUDE.md's extraction scope grows over time
    (classes/functions/methods/interfaces/enums/variables/namespaces
    today), and a closed enum would need a migration for every future
    addition. ``visibility`` is a genuinely small, stable vocabulary, so
    it is constrained.
    """

    __tablename__ = "symbols"
    __table_args__ = (
        # Bare token "visibility", not "ck_symbols_visibility" — see the
        # matching note on Repository.status for why a pre-qualified name
        # would double up under the naming convention in models/base.py.
        CheckConstraint(_visibility_check_sql, name="visibility"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_symbol_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("symbols.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    qualified_name: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    symbol_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="public")
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    file: Mapped["File"] = relationship(back_populates="symbols")
    parent: Mapped[Optional["Symbol"]] = relationship("Symbol", back_populates="children", remote_side=[id])
    children: Mapped[list["Symbol"]] = relationship("Symbol", back_populates="parent")
