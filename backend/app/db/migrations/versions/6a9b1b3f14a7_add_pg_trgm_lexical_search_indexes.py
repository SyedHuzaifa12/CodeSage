"""add pg_trgm extension and lexical-search trigram indexes

Revision ID: 6a9b1b3f14a7
Revises: 8f64382343f9
Create Date: 2026-09-06 00:00:00.000000

Sprint 4 (Retrieval). Lexical/keyword retrieval over code identifiers
(``AuthService``, ``getUserById``, ...) needs substring/fuzzy matching
that a plain B-tree index can't do efficiently — ``pg_trgm`` is
PostgreSQL's built-in trigram-similarity extension, not new
infrastructure, matching CLAUDE.md's "no unnecessary infrastructure"
constraint for lexical search. GIN trigram indexes back both
``ILIKE '%term%'`` and the ``similarity()`` scoring function used by
``app/retrieval/repository.py``.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6a9b1b3f14a7'
down_revision: Union[str, Sequence[str], None] = '8f64382343f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX ix_symbols_name_trgm ON symbols USING gin (name gin_trgm_ops)")
    op.execute("CREATE INDEX ix_symbols_qualified_name_trgm ON symbols USING gin (qualified_name gin_trgm_ops)")
    op.execute("CREATE INDEX ix_files_path_trgm ON files USING gin (path gin_trgm_ops)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_files_path_trgm")
    op.execute("DROP INDEX IF EXISTS ix_symbols_qualified_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_symbols_name_trgm")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
