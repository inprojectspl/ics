"""asset pin

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-12

The pin timestamp orders pins (most recently pinned first). Partial index
because most assets are unpinned.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("pinned_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_assets_pinned",
        "assets",
        ["owner_id", "pinned_at"],
        postgresql_where=sa.text("pinned_at IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_assets_pinned", table_name="assets")
    op.drop_column("assets", "pinned_at")
