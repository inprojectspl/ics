"""Commit scoped publication results with their assets.

Revision ID: 0046
Revises: 0045
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publication_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "principal_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("order_id", sa.String(200), nullable=False),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("publication_id", sa.String(200), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "principal_id",
            "project_id",
            "order_id",
            "role",
            "publication_id",
            name="uq_publication_receipt_scope",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_publication_receipts_asset_id", "publication_receipts", ["asset_id"])


def downgrade() -> None:
    op.drop_table("publication_receipts")
