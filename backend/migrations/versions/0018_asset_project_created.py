"""index assets (project_id, created_at DESC) for get_project pagination

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-17

ix_asset_project_updated (0014) cannot serve the created_at DESC sort of
get_project; this partial index reads the first page in index order.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_project_created "
        "ON assets (project_id, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_asset_project_created")
