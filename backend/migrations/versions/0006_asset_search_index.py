"""asset search index

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-12

md kinds only; html_bundle stays NULL because sandboxed HTML is reviewed by
its owner, not found through free-text search. Partial on deleted_at IS NULL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # pg_trgm is bundled with stock Postgres but needs an explicit CREATE EXTENSION.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column("assets", sa.Column("search_content", sa.Text(), nullable=True))
    op.execute(
        "CREATE INDEX ix_assets_search_content_trgm "
        "ON assets USING gin (search_content gin_trgm_ops) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_assets_search_content_trgm")
    op.drop_column("assets", "search_content")
    # Leave the extension installed: other apps in the cluster may use it.
