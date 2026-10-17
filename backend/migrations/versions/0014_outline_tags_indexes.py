"""Asset.tags + outline columns + perf indexes

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-15

Tags, cached outline columns (rebuilt by Arq) and indexes for the
cursor-paginated /api/assets/index query. Indexes use IF NOT EXISTS for re-runs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Asset.tags
    op.add_column(
        "assets",
        sa.Column(
            "tags",
            sa.dialects.postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_asset_tags_gin ON assets USING GIN (tags)")

    # Asset outline columns
    op.add_column(
        "assets", sa.Column("outline_json", sa.dialects.postgresql.JSONB(), nullable=True)
    )
    op.add_column("assets", sa.Column("outline_version", sa.Integer(), nullable=True))
    op.add_column(
        "assets",
        sa.Column(
            "outline_status",
            sa.String(16),
            server_default="stale",
            nullable=False,
        ),
    )
    op.add_column(
        "assets", sa.Column("outline_built_at", sa.TIMESTAMP(timezone=True), nullable=True)
    )
    op.add_column("assets", sa.Column("outline_error", sa.Text(), nullable=True))
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_outline_stale "
        "ON assets (outline_status, updated_at) "
        "WHERE outline_status IN ('stale','building')"
    )

    # Composite + partial indexes for /index filters
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_owner_updated "
        "ON assets (owner_id, updated_at DESC) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_project_updated "
        "ON assets (project_id, updated_at DESC) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_kind_updated "
        "ON assets (owner_id, kind, updated_at DESC) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_pinned "
        "ON assets (owner_id, pinned_at DESC) "
        "WHERE pinned_at IS NOT NULL AND deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_slug_active ON assets (slug) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_updated_id "
        "ON assets (updated_at DESC, id DESC) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_asset_share_user_granted "
        "ON asset_shares (user_id, granted_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_project_member_user_accepted "
        "ON project_members (user_id) WHERE accepted_at IS NOT NULL"
    )

    # Bias autovacuum on the hot table
    op.execute("ALTER TABLE assets SET (autovacuum_vacuum_scale_factor = 0.05)")


def downgrade() -> None:
    op.execute("ALTER TABLE assets RESET (autovacuum_vacuum_scale_factor)")

    for ix in [
        "ix_project_member_user_accepted",
        "ix_asset_share_user_granted",
        "ix_asset_updated_id",
        "ix_asset_slug_active",
        "ix_asset_pinned",
        "ix_asset_kind_updated",
        "ix_asset_project_updated",
        "ix_asset_owner_updated",
        "ix_asset_outline_stale",
        "ix_asset_tags_gin",
    ]:
        op.execute(f"DROP INDEX IF EXISTS {ix}")

    op.drop_column("assets", "outline_error")
    op.drop_column("assets", "outline_built_at")
    op.drop_column("assets", "outline_status")
    op.drop_column("assets", "outline_version")
    op.drop_column("assets", "outline_json")
    op.drop_column("assets", "tags")
