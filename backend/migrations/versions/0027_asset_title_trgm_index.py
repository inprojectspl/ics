"""trigram index for the free-text title filter on the MCP listing

Revision ID: 0027
Revises: 0026
Create Date: 2026-09-21

The title filter on GET /index matches lower(title) with a leading
wildcard, which a b-tree cannot serve. Mirrors the 0006 trigram index.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pg_trgm already installed by 0006; the guard keeps this migration
    # standalone if that one is ever squashed away.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX ix_assets_title_lower_trgm "
        "ON assets USING gin (lower(title) gin_trgm_ops) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_assets_title_lower_trgm")
