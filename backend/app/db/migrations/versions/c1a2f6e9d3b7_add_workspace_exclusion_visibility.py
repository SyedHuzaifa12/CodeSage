"""add workspace noise-exclusion visibility columns

Revision ID: c1a2f6e9d3b7
Revises: a1f3c7e9b2d4
Create Date: 2026-11-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1a2f6e9d3b7'
down_revision: Union[str, Sequence[str], None] = 'a1f3c7e9b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'repository_workspace',
        sa.Column('excluded_files_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'repository_workspace',
        sa.Column('excluded_by_reason', sa.JSON(), nullable=False, server_default='{}'),
    )
    op.add_column(
        'repository_workspace',
        sa.Column('excluded_samples', sa.JSON(), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('repository_workspace', 'excluded_samples')
    op.drop_column('repository_workspace', 'excluded_by_reason')
    op.drop_column('repository_workspace', 'excluded_files_count')
