"""update repository status values

Revision ID: 720c10308d09
Revises: e34e1c58885b
Create Date: 2026-07-12 22:35:37.700529

Replaces the placeholder status vocabulary from the initial schema
(pending/cloning/parsing/indexing/completed/failed) with the one
Sprint 1A defines for the Repository module: pending/cloning/ready/
failed/deleted. Autogenerate does not detect CheckConstraint text
changes, so this migration is hand-written.

Uses raw DDL via ``op.execute`` rather than ``op.drop_constraint``/
``op.create_check_constraint`` — those re-apply the naming convention
to whatever name is passed, which double-prefixes an already-qualified
name like ``ck_repositories_status`` (the exact bug the initial
migration hit and fixed). Raw DDL avoids that reprocessing entirely.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '720c10308d09'
down_revision: Union[str, Sequence[str], None] = 'e34e1c58885b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_STATUSES = ("pending", "cloning", "parsing", "indexing", "completed", "failed")
NEW_STATUSES = ("pending", "cloning", "ready", "failed", "deleted")

_CONSTRAINT_NAME = "ck_repositories_status"


def _in_clause(values: tuple[str, ...]) -> str:
    return "status IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(f"ALTER TABLE repositories DROP CONSTRAINT {_CONSTRAINT_NAME}")
    op.execute(f"ALTER TABLE repositories ADD CONSTRAINT {_CONSTRAINT_NAME} CHECK ({_in_clause(NEW_STATUSES)})")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"ALTER TABLE repositories DROP CONSTRAINT {_CONSTRAINT_NAME}")
    op.execute(f"ALTER TABLE repositories ADD CONSTRAINT {_CONSTRAINT_NAME} CHECK ({_in_clause(OLD_STATUSES)})")
