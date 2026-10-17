"""duplicate dismissals

Revision ID: 0039
Revises: 0038
Create Date: 2026-09-26

Remembers pairs of assets a person marked "not a duplicate", so the project
hygiene suggestions stop proposing them. Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "duplicate_dismissals",
        sa.Column(
            "asset_a_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "asset_b_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "dismissed_by",
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
        sa.CheckConstraint("asset_a_id < asset_b_id", name="ck_duplicate_dismissals_order"),
    )
    # The primary key leads with asset_a_id, so it already serves that FK.
    op.create_index("ix_duplicate_dismissals_asset_b", "duplicate_dismissals", ["asset_b_id"])
    op.create_index(
        "ix_duplicate_dismissals_dismissed_by", "duplicate_dismissals", ["dismissed_by"]
    )


def downgrade() -> None:
    op.drop_table("duplicate_dismissals")
