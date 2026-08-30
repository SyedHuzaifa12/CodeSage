"""add conversation metadata (intent, verification_status, total_latency_ms)

Revision ID: b4bca69510a2
Revises: 6a9b1b3f14a7
Create Date: 2026-09-13 00:00:00.000000

Sprint 5 (AI Engine). Additive, nullable columns on the ``conversations``
table — created in the initial schema (Sprint 0B) but never written to
until this sprint, so there is no existing data to migrate. The CHECK
constraint is added via raw DDL (``op.execute``), not
``op.create_check_constraint``, because this table already exists —
see d7a2d76d2cc4's docstring for why that distinction matters under
the naming convention in ``models/base.py``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4bca69510a2'
down_revision: Union[str, Sequence[str], None] = '6a9b1b3f14a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VALID_VERIFICATION_STATUSES = ("supported", "partially_supported", "insufficient_evidence", "contradicted")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('conversations', sa.Column('intent', sa.String(length=32), nullable=True))
    op.add_column('conversations', sa.Column('verification_status', sa.String(length=24), nullable=True))
    op.add_column('conversations', sa.Column('total_latency_ms', sa.Integer(), nullable=True))
    op.execute(
        "ALTER TABLE conversations ADD CONSTRAINT ck_conversations_verification_status "
        "CHECK (verification_status IN ("
        + ", ".join(f"'{value}'" for value in VALID_VERIFICATION_STATUSES)
        + "))"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE conversations DROP CONSTRAINT ck_conversations_verification_status")
    op.drop_column('conversations', 'total_latency_ms')
    op.drop_column('conversations', 'verification_status')
    op.drop_column('conversations', 'intent')
