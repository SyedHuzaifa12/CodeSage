"""Report ORM model — a generated engineering document for a repository."""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository

VALID_REPORT_TYPES = ("summary", "onboarding", "architecture", "impact")

_report_type_check_sql = "report_type IN (" + ", ".join(f"'{value}'" for value in VALID_REPORT_TYPES) + ")"


class Report(Base, TimestampMixin):
    """A generated engineering report (onboarding, architecture, summary, impact)."""

    __tablename__ = "reports"
    # Bare token "report_type", not "ck_reports_report_type" — see the
    # matching note in models/repository.py on why a pre-qualified name
    # would double up under the naming convention.
    __table_args__ = (CheckConstraint(_report_type_check_sql, name="report_type"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    repository: Mapped["Repository"] = relationship(back_populates="reports")
