"""add indexing_jobs queue table (ADR-028)

Revision ID: a7c2e9b4d1f6
Revises: f5a1c3d9b7e2
Create Date: 2026-11-16 00:00:00.000000

Additive only: a new table, nothing existing is altered.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c2e9b4d1f6'
down_revision: Union[str, Sequence[str], None] = 'f5a1c3d9b7e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'indexing_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('repository_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kind', sa.String(length=24), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('available_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('claimed_by', sa.String(length=128), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('max_files', sa.Integer(), nullable=True),
        sa.Column('max_bytes', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("kind IN ('full_index', 'knowledge_reindex')", name=op.f('ck_indexing_jobs_kind')),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name=op.f('ck_indexing_jobs_status')
        ),
        sa.ForeignKeyConstraint(
            ['repository_id'], ['repositories.id'],
            name=op.f('fk_indexing_jobs_repository_id_repositories'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_indexing_jobs')),
    )
    op.create_index(op.f('ix_indexing_jobs_repository_id'), 'indexing_jobs', ['repository_id'], unique=False)
    op.create_index('ix_indexing_jobs_claim', 'indexing_jobs', ['status', 'available_at'], unique=False)
    op.create_index(
        'uq_indexing_jobs_one_active_per_repository', 'indexing_jobs', ['repository_id'], unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_indexing_jobs_one_active_per_repository', table_name='indexing_jobs',
                  postgresql_where=sa.text("status IN ('queued', 'running')"))
    op.drop_index('ix_indexing_jobs_claim', table_name='indexing_jobs')
    op.drop_index(op.f('ix_indexing_jobs_repository_id'), table_name='indexing_jobs')
    op.drop_table('indexing_jobs')
