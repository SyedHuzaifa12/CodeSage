"""Symbol ORM model — a function, class, method, or other extracted code symbol."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.file import File


class Symbol(Base, TimestampMixin):
    """A function, class, method, interface, or other symbol extracted from a file."""

    __tablename__ = "symbols"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    symbol_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    signature: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    file: Mapped["File"] = relationship(back_populates="symbols")
