"""per-user pins

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-03

assets.pinned_at was shared by everyone with access. Pins become a
user-asset relation; existing pins go to the asset owner, who most likely
set them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_pins",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "asset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "pinned_at",
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # A CASCADE FK needs an index: without it, deleting an asset means a Seq
    # Scan of asset_pins. The hot path (user-scoped lookup) uses the composite PK.
    op.create_index("ix_asset_pins_asset_id", "asset_pins", ["asset_id"])
    op.execute(
        "INSERT INTO asset_pins (user_id, asset_id, pinned_at) "
        "SELECT owner_id, id, pinned_at FROM assets WHERE pinned_at IS NOT NULL"
    )
    # Dropped explicitly (not via DROP COLUMN cascade) so downgrade() recreates
    # exactly these. IF EXISTS: 0014 used IF NOT EXISTS, so they may be missing.
    op.execute("DROP INDEX IF EXISTS ix_assets_pinned")  # from 0009
    op.execute("DROP INDEX IF EXISTS ix_asset_pinned")  # from 0014
    op.drop_column("assets", "pinned_at")


def downgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("pinned_at", TIMESTAMP(timezone=True), nullable=True),
    )
    # Lossy return to global state: per asset, take the owner's pin, or the
    # most recent pin of any user when the owner has none.
    op.execute(
        "UPDATE assets SET pinned_at = sub.pinned_at FROM ("
        "  SELECT DISTINCT ON (ap.asset_id) ap.asset_id, ap.pinned_at"
        "  FROM asset_pins ap JOIN assets a ON a.id = ap.asset_id"
        "  ORDER BY ap.asset_id, (ap.user_id = a.owner_id) DESC, ap.pinned_at DESC"
        ") sub WHERE assets.id = sub.asset_id"
    )
    # Identical to 0009 and 0014; a downgrade below 0009 needs them for
    # op.drop_index.
    op.create_index(
        "ix_assets_pinned",
        "assets",
        ["owner_id", "pinned_at"],
        postgresql_where=sa.text("pinned_at IS NOT NULL AND deleted_at IS NULL"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_pinned "
        "ON assets (owner_id, pinned_at DESC) "
        "WHERE pinned_at IS NOT NULL AND deleted_at IS NULL"
    )
    op.drop_index("ix_asset_pins_asset_id", table_name="asset_pins")
    op.drop_table("asset_pins")
