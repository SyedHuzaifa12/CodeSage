"""add users, refresh_tokens and repository ownership (ADR-027)

Revision ID: f5a1c3d9b7e2
Revises: d4e8a1b0c6f2
Create Date: 2026-11-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f5a1c3d9b7e2'
down_revision: Union[str, Sequence[str], None] = 'd4e8a1b0c6f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('github_id', sa.BigInteger(), nullable=True),
        sa.Column('github_login', sa.String(length=255), nullable=True),
        sa.Column('display_name', sa.String(length=255), nullable=True),
        sa.Column('avatar_url', sa.String(length=1024), nullable=True),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('guest_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("kind IN ('guest', 'user')", name=op.f('ck_users_kind')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
        sa.UniqueConstraint('github_id', name=op.f('uq_users_github_id')),
    )
    op.create_index('ix_users_guest_expires_at', 'users', ['guest_expires_at'], unique=False)

    op.create_table(
        'refresh_tokens',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('family_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('replaced_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['user_id'], ['users.id'], name=op.f('fk_refresh_tokens_user_id_users'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_refresh_tokens')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_refresh_tokens_token_hash')),
    )
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_index('ix_refresh_tokens_family_id', 'refresh_tokens', ['family_id'], unique=False)

    op.add_column('repositories', sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        'repositories',
        sa.Column('is_demo', sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_index(op.f('ix_repositories_owner_id'), 'repositories', ['owner_id'], unique=False)
    op.create_foreign_key(
        op.f('fk_repositories_owner_id_users'), 'repositories', 'users', ['owner_id'], ['id'], ondelete='RESTRICT'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('fk_repositories_owner_id_users'), 'repositories', type_='foreignkey')
    op.drop_index(op.f('ix_repositories_owner_id'), table_name='repositories')
    op.drop_column('repositories', 'is_demo')
    op.drop_column('repositories', 'owner_id')

    op.drop_index('ix_refresh_tokens_family_id', table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')

    op.drop_index('ix_users_guest_expires_at', table_name='users')
    op.drop_table('users')
