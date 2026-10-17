"""comments

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-12

Visible only in the owner viewer: share-token viewers never see the thread,
so internal context cannot leak alongside the document. Dropped in 0020.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "asset_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    # Asset thread lookups + author-of-comment queries are the two hot paths.
    op.create_index("ix_comments_asset_created", "comments", ["asset_id", "created_at"])
    op.create_index("ix_comments_author", "comments", ["author_id"])


def downgrade() -> None:
    op.drop_index("ix_comments_author", table_name="comments")
    op.drop_index("ix_comments_asset_created", table_name="comments")
    op.drop_table("comments")
