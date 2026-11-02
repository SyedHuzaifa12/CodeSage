"""add repository celery_task_id column (ADR-026)

Revision ID: d4e8a1b0c6f2
Revises: c1a2f6e9d3b7
Create Date: 2026-11-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e8a1b0c6f2'
down_revision: Union[str, Sequence[str], None] = 'c1a2f6e9d3b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'repositories',
        sa.Column('celery_task_id', sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('repositories', 'celery_task_id')
