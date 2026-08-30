"""add knowledge_chunks and knowledge_index_state tables

Revision ID: 8f64382343f9
Revises: bfd24a75f425
Create Date: 2026-08-30 00:00:00.000000

New tables only (Sprint 3, Knowledge module). CHECK constraints are
attached directly in ``create_table`` via ``op.f()``, same as
``repository_workspace``/``repository_intelligence`` before it — safe
for brand-new tables (see those migrations' docstrings for why this
differs from altering an *existing* table's constraints).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8f64382343f9'
down_revision: Union[str, Sequence[str], None] = 'bfd24a75f425'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VALID_CHUNK_TYPES = ("symbol", "symbol_split", "fallback")
VALID_KNOWLEDGE_STATUSES = ("pending", "indexing", "ready", "failed")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'knowledge_chunks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('file_id', sa.UUID(), nullable=False),
        sa.Column('symbol_id', sa.UUID(), nullable=True),
        sa.Column('chunk_index', sa.Integer(), nullable=False),
        sa.Column('chunk_type', sa.String(length=16), nullable=False),
        sa.Column('start_line', sa.Integer(), nullable=False),
        sa.Column('end_line', sa.Integer(), nullable=False),
        sa.Column('char_count', sa.Integer(), nullable=False),
        sa.Column('language', sa.String(length=64), nullable=True),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('file_content_hash', sa.String(length=64), nullable=False),
        sa.Column('embedding_model_version', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "chunk_type IN (" + ", ".join(f"'{v}'" for v in VALID_CHUNK_TYPES) + ")",
            name=op.f('ck_knowledge_chunks_chunk_type'),
        ),
        sa.ForeignKeyConstraint(
            ['repository_id'], ['repositories.id'],
            name=op.f('fk_knowledge_chunks_repository_id_repositories'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['file_id'], ['files.id'],
            name=op.f('fk_knowledge_chunks_file_id_files'), ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['symbol_id'], ['symbols.id'],
            name=op.f('fk_knowledge_chunks_symbol_id_symbols'), ondelete='SET NULL',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_chunks')),
        sa.UniqueConstraint('file_id', 'chunk_index', name='uq_knowledge_chunks_file_chunk_index'),
    )
    op.create_index(op.f('ix_knowledge_chunks_repository_id'), 'knowledge_chunks', ['repository_id'], unique=False)
    op.create_index(op.f('ix_knowledge_chunks_file_id'), 'knowledge_chunks', ['file_id'], unique=False)
    op.create_index(op.f('ix_knowledge_chunks_symbol_id'), 'knowledge_chunks', ['symbol_id'], unique=False)
    op.create_index(op.f('ix_knowledge_chunks_content_hash'), 'knowledge_chunks', ['content_hash'], unique=False)
    op.create_index(
        op.f('ix_knowledge_chunks_embedding_model_version'), 'knowledge_chunks', ['embedding_model_version'], unique=False
    )

    op.create_table(
        'knowledge_index_state',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('repository_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('progress', sa.Integer(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('embedding_model_version', sa.String(length=128), nullable=True),
        sa.Column('total_files_considered', sa.Integer(), nullable=False),
        sa.Column('total_files_skipped_unchanged', sa.Integer(), nullable=False),
        sa.Column('total_files_failed', sa.Integer(), nullable=False),
        sa.Column('total_chunks', sa.Integer(), nullable=False),
        sa.Column('total_chunks_from_cache', sa.Integer(), nullable=False),
        sa.Column('total_chunks_embedded_fresh', sa.Integer(), nullable=False),
        sa.Column('last_indexed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('chunking_ms', sa.Integer(), nullable=True),
        sa.Column('embedding_ms', sa.Integer(), nullable=True),
        sa.Column('upsert_ms', sa.Integer(), nullable=True),
        sa.Column('total_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{v}'" for v in VALID_KNOWLEDGE_STATUSES) + ")",
            name=op.f('ck_knowledge_index_state_status'),
        ),
        sa.ForeignKeyConstraint(
            ['repository_id'], ['repositories.id'],
            name=op.f('fk_knowledge_index_state_repository_id_repositories'), ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_index_state')),
        sa.UniqueConstraint('repository_id', name=op.f('uq_knowledge_index_state_repository_id')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('knowledge_index_state')
    op.drop_index(op.f('ix_knowledge_chunks_embedding_model_version'), table_name='knowledge_chunks')
    op.drop_index(op.f('ix_knowledge_chunks_content_hash'), table_name='knowledge_chunks')
    op.drop_index(op.f('ix_knowledge_chunks_symbol_id'), table_name='knowledge_chunks')
    op.drop_index(op.f('ix_knowledge_chunks_file_id'), table_name='knowledge_chunks')
    op.drop_index(op.f('ix_knowledge_chunks_repository_id'), table_name='knowledge_chunks')
    op.drop_table('knowledge_chunks')
