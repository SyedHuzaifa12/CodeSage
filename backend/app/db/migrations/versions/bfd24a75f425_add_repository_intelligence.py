"""add repository_intelligence table

Revision ID: bfd24a75f425
Revises: d7a2d76d2cc4
Create Date: 2026-07-13 02:20:00.000000

New table only (Sprint 2B) — the CHECK constraint is attached directly
in ``create_table`` via ``op.f()``, same as ``repository_workspace``'s
own status constraint (e86c92b99f15): safe here because ``op.f()`` on a
literal already-qualified name is just a "don't re-derive this" marker,
not a naming-convention re-application — that re-application bug only
bites ``op.create_check_constraint``/``op.drop_constraint`` calls
against an *existing* table's metadata (see d7a2d76d2cc4's docstring).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfd24a75f425'
down_revision: Union[str, Sequence[str], None] = 'd7a2d76d2cc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VALID_INTELLIGENCE_STATUSES = ("pending", "analyzing", "ready", "failed")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'repository_intelligence',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('total_symbols', sa.Integer(), nullable=False),
        sa.Column('total_classes', sa.Integer(), nullable=False),
        sa.Column('total_interfaces', sa.Integer(), nullable=False),
        sa.Column('total_enums', sa.Integer(), nullable=False),
        sa.Column('total_functions', sa.Integer(), nullable=False),
        sa.Column('total_methods', sa.Integer(), nullable=False),
        sa.Column('total_variables', sa.Integer(), nullable=False),
        sa.Column('total_namespaces', sa.Integer(), nullable=False),
        sa.Column('total_imports', sa.Integer(), nullable=False),
        sa.Column('total_calls', sa.Integer(), nullable=False),
        sa.Column('inheritance_count', sa.Integer(), nullable=False),
        sa.Column('dependency_count', sa.Integer(), nullable=False),
        sa.Column('circular_dependencies', sa.JSON(), nullable=False),
        sa.Column('orphan_files', sa.JSON(), nullable=False),
        sa.Column('languages', sa.JSON(), nullable=False),
        sa.Column('architecture_hints', sa.JSON(), nullable=False),
        sa.Column('entry_points', sa.JSON(), nullable=False),
        sa.Column('largest_modules', sa.JSON(), nullable=False),
        sa.Column('dependency_hotspots', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "status IN ("
            + ", ".join(f"'{value}'" for value in VALID_INTELLIGENCE_STATUSES)
            + ")",
            name=op.f('ck_repository_intelligence_status'),
        ),
        sa.ForeignKeyConstraint(
            ['repository_id'], ['repositories.id'],
            name=op.f('fk_repository_intelligence_repository_id_repositories'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_repository_intelligence')),
        sa.UniqueConstraint('repository_id', name=op.f('uq_repository_intelligence_repository_id')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('repository_intelligence')
