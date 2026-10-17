"""track content changes separately from row updates

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-26

updated_at moves on every row write; content_updated_at/by only when a
version is written. Backfill: newest version (author or owner), else the
asset's created_at and owner.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL_SQL = (
    """
    UPDATE assets AS a
    SET content_updated_at = latest.created_at,
        content_updated_by = coalesce(latest.created_by, a.owner_id)
    FROM (
        SELECT DISTINCT ON (asset_id) asset_id, created_at, created_by
        FROM asset_versions
        ORDER BY asset_id, created_at DESC, version DESC
    ) AS latest
    WHERE latest.asset_id = a.id
    """,
    """
    UPDATE assets
    SET content_updated_at = created_at, content_updated_by = owner_id
    WHERE content_updated_at IS NULL
    """,
)


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("content_updated_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column(
            "content_updated_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # The FK is SET NULL: without the index, deleting a user scans assets.
    op.create_index("ix_assets_content_updated_by", "assets", ["content_updated_by"])
    for statement in BACKFILL_SQL:
        op.execute(statement)


def downgrade() -> None:
    op.drop_index("ix_assets_content_updated_by", table_name="assets")
    op.drop_column("assets", "content_updated_by")
    op.drop_column("assets", "content_updated_at")
