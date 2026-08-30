"""extend reports for sprint 6 (repository intelligence reports)

Revision ID: a1f3c7e9b2d4
Revises: b4bca69510a2
Create Date: 2026-08-30 00:00:00.000000

Sprint 6 (Reports). The ``reports`` table was created in the initial
schema (Sprint 0B) but has zero production rows — same situation
``conversations`` was in pre-Sprint-5 (see b4bca69510a2). This migration:

1. Widens ``report_type``'s CHECK constraint to add ``dependency_risk``
   and ``health`` (Sprint 6's two new report types; ``impact`` stays
   reserved/unused per ADR-016, not repurposed).
2. Adds a ``status`` column + CHECK constraint for the append-only
   generation lifecycle (``pending``/``generating``/``ready``/``failed``).
3. Adds additive, nullable-where-sensible columns for structured
   rendering (``title``/``summary``/``sections``/``evidence``/
   ``diagrams``/``generation_metadata``), staleness detection
   (``repository_version``), and failure reporting (``error_message``,
   ``generated_at``).
4. Adds an index on ``(repository_id, report_type, created_at)`` — the
   query "the latest row for a given repository+type" is now the
   primary access pattern (reports are append-only, see ADR-021).

Both existing CHECK constraints on this table were created via
``CheckConstraint(..., name="report_type")`` under the naming
convention in ``models/base.py``, which resolves to
``ck_reports_report_type`` in the actual database — altering an
existing constraint on an existing table requires raw DDL
(``op.execute``), not ``op.create_check_constraint``, which would
double-prefix the name. See b4bca69510a2's docstring for the same
pattern applied to ``conversations``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3c7e9b2d4'
down_revision: Union[str, Sequence[str], None] = 'b4bca69510a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_REPORT_TYPES = ("summary", "onboarding", "architecture", "impact")
NEW_REPORT_TYPES = ("summary", "onboarding", "architecture", "impact", "dependency_risk", "health")
VALID_REPORT_STATUSES = ("pending", "generating", "ready", "failed")


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TABLE reports DROP CONSTRAINT ck_reports_report_type")
    op.execute(
        "ALTER TABLE reports ADD CONSTRAINT ck_reports_report_type "
        "CHECK (report_type IN (" + ", ".join(f"'{value}'" for value in NEW_REPORT_TYPES) + "))"
    )

    op.add_column('reports', sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'))
    op.execute(
        "ALTER TABLE reports ADD CONSTRAINT ck_reports_status "
        "CHECK (status IN (" + ", ".join(f"'{value}'" for value in VALID_REPORT_STATUSES) + "))"
    )
    op.alter_column('reports', 'status', server_default=None)

    op.add_column('reports', sa.Column('generated_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('reports', sa.Column('repository_version', sa.String(length=255), nullable=True))
    op.add_column('reports', sa.Column('title', sa.String(length=255), nullable=True))
    op.add_column('reports', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column('reports', sa.Column('sections', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('reports', sa.Column('evidence', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('reports', sa.Column('diagrams', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('reports', sa.Column('generation_metadata', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('reports', sa.Column('error_message', sa.Text(), nullable=True))
    for column in ('sections', 'evidence', 'diagrams', 'generation_metadata'):
        op.alter_column('reports', column, server_default=None)

    op.create_index(
        'ix_reports_repository_type_created', 'reports', ['repository_id', 'report_type', 'created_at']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_reports_repository_type_created', table_name='reports')
    op.drop_column('reports', 'error_message')
    op.drop_column('reports', 'generation_metadata')
    op.drop_column('reports', 'diagrams')
    op.drop_column('reports', 'evidence')
    op.drop_column('reports', 'sections')
    op.drop_column('reports', 'summary')
    op.drop_column('reports', 'title')
    op.drop_column('reports', 'repository_version')
    op.drop_column('reports', 'generated_at')
    op.execute("ALTER TABLE reports DROP CONSTRAINT ck_reports_status")
    op.drop_column('reports', 'status')

    op.execute("ALTER TABLE reports DROP CONSTRAINT ck_reports_report_type")
    op.execute(
        "ALTER TABLE reports ADD CONSTRAINT ck_reports_report_type "
        "CHECK (report_type IN (" + ", ".join(f"'{value}'" for value in OLD_REPORT_TYPES) + "))"
    )
