"""asset project shares

Revision ID: 0035
Revises: 0034
Create Date: 2026-09-26

ADR-0017. Gives the members of another project a viewer or editor role on
an asset while `assets.project_id` stays its home. Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_project_shares",
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("role IN ('viewer','editor')", name="ck_asset_project_shares_role"),
    )
    # The primary key leads with asset_id, so it already serves that FK.
    op.create_index("ix_asset_project_shares_project", "asset_project_shares", ["project_id"])
    op.create_index("ix_asset_project_shares_created_by", "asset_project_shares", ["created_by"])


def downgrade() -> None:
    op.drop_table("asset_project_shares")
