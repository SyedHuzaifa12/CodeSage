"""add symbol metadata and repository indexing status

Revision ID: d7a2d76d2cc4
Revises: e86c92b99f15
Create Date: 2026-07-13 01:50:02.544486

Autogenerate does not detect CheckConstraints on new columns (the same
limitation hit in earlier migrations), so the ``indexing_status`` and
``visibility`` constraints are added by hand via raw DDL — using
``op.create_check_constraint`` here would re-apply the naming
convention to an already-bare name and double-prefix it, exactly the
bug fixed in the initial-schema and status-update migrations.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a2d76d2cc4'
down_revision: Union[str, Sequence[str], None] = 'e86c92b99f15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VALID_INDEXING_STATUSES = ("not_started", "indexing", "indexed", "failed")
VALID_SYMBOL_VISIBILITIES = ("public", "protected", "private", "package-private")


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'repositories',
        sa.Column('indexing_status', sa.String(length=16), nullable=False, server_default='not_started'),
    )
    op.alter_column('repositories', 'indexing_status', server_default=None)
    op.execute(
        f"ALTER TABLE repositories ADD CONSTRAINT ck_repositories_indexing_status "
        f"CHECK ({_in_clause('indexing_status', VALID_INDEXING_STATUSES)})"
    )

    op.add_column('symbols', sa.Column('parent_symbol_id', sa.UUID(), nullable=True))
    op.add_column(
        'symbols', sa.Column('qualified_name', sa.String(length=1024), nullable=False, server_default='')
    )
    op.alter_column('symbols', 'qualified_name', server_default=None)
    op.add_column(
        'symbols', sa.Column('visibility', sa.String(length=16), nullable=False, server_default='public')
    )
    op.alter_column('symbols', 'visibility', server_default=None)
    op.create_index(op.f('ix_symbols_parent_symbol_id'), 'symbols', ['parent_symbol_id'], unique=False)
    op.create_index(op.f('ix_symbols_qualified_name'), 'symbols', ['qualified_name'], unique=False)
    op.create_foreign_key(
        op.f('fk_symbols_parent_symbol_id_symbols'), 'symbols', 'symbols', ['parent_symbol_id'], ['id'], ondelete='CASCADE'
    )
    op.execute(
        f"ALTER TABLE symbols ADD CONSTRAINT ck_symbols_visibility "
        f"CHECK ({_in_clause('visibility', VALID_SYMBOL_VISIBILITIES)})"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE symbols DROP CONSTRAINT ck_symbols_visibility")
    op.drop_constraint(op.f('fk_symbols_parent_symbol_id_symbols'), 'symbols', type_='foreignkey')
    op.drop_index(op.f('ix_symbols_qualified_name'), table_name='symbols')
    op.drop_index(op.f('ix_symbols_parent_symbol_id'), table_name='symbols')
    op.drop_column('symbols', 'visibility')
    op.drop_column('symbols', 'qualified_name')
    op.drop_column('symbols', 'parent_symbol_id')
    op.execute("ALTER TABLE repositories DROP CONSTRAINT ck_repositories_indexing_status")
    op.drop_column('repositories', 'indexing_status')
