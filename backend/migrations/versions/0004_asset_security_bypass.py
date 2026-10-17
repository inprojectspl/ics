"""asset security bypass

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-12

A new version of a critical asset always resets the bypass to False, so a
fresh scan runs and the admin review starts over.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "assets",
        sa.Column("security_bypass", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "assets",
        sa.Column("security_bypass_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column(
            "security_bypass_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "assets",
        sa.Column("security_bypass_reason", sa.Text(), nullable=True),
    )
    # Partial index for the admin review queue: most assets are clean so
    # we skip them, leaving an index of just the pending ones (small).
    op.create_index(
        "ix_assets_security_pending",
        "assets",
        ["created_at"],
        postgresql_where=sa.text(
            "security_status = 'critical' AND security_bypass = false AND deleted_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_assets_security_pending", table_name="assets")
    op.drop_column("assets", "security_bypass_reason")
    op.drop_column("assets", "security_bypass_by")
    op.drop_column("assets", "security_bypass_at")
    op.drop_column("assets", "security_bypass")
