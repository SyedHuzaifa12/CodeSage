"""Report ORM model — a generated engineering document for a repository.

Sprint 6 extends the Sprint 0B skeleton (``report_type``/``content``
only, zero production rows) additively: new nullable-where-sensible
columns for structured rendering (``title``/``summary``/``sections``/
``evidence``/``diagrams``/``generation_metadata``), a generation
lifecycle (``status``/``generated_at``/``error_message``), and a
``repository_version`` fingerprint for staleness detection. ``content``
stays ``NOT NULL`` for backward compatibility with the original
contract — Sprint 6 populates it with a deterministic textual rendering
of the structured report (see ``reports/utils.py::render_content_text``)
rather than dropping it.

Reports are APPEND-ONLY: one new row per generation attempt, never
updated in place. "The latest report" of a given type is the most
recent row for ``(repository_id, report_type)`` — see ADR-021. This
means a failed regeneration can never corrupt or replace the last good
``ready`` row.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.repository import Repository

VALID_REPORT_TYPES = ("summary", "onboarding", "architecture", "impact", "dependency_risk", "health")
VALID_REPORT_STATUSES = ("pending", "generating", "ready", "failed")

_report_type_check_sql = "report_type IN (" + ", ".join(f"'{value}'" for value in VALID_REPORT_TYPES) + ")"
_status_check_sql = "status IN (" + ", ".join(f"'{value}'" for value in VALID_REPORT_STATUSES) + ")"


class Report(Base, TimestampMixin):
    """A generated engineering report (onboarding, architecture, summary, dependency_risk, health, impact)."""

    __tablename__ = "reports"
    __table_args__ = (
        # Bare tokens, not "ck_reports_report_type"/"ck_reports_status" —
        # see the matching note in models/repository.py on why a
        # pre-qualified name would double up under the naming convention.
        CheckConstraint(_report_type_check_sql, name="report_type"),
        CheckConstraint(_status_check_sql, name="status"),
        Index("ix_reports_repository_type_created", "repository_id", "report_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    repository_version: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sections: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    evidence: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    diagrams: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    generation_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    repository: Mapped["Repository"] = relationship(back_populates="reports")
