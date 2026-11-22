"""storage cleanup queue

Revision ID: 0053
Revises: 0052
Create Date: 2026-11-22

Prefixes whose rows a purge or an account deletion removed, kept until the
files are deleted, so a crash between the commit and the storage calls does
not orphan them and a restore cannot race a purge.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "storage_cleanup",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("storage_cleanup")
