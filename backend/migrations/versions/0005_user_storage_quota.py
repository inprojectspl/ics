"""user storage quota

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-12

Default 1 GiB. The running sum is not denormalized: a counter would drift
under concurrent upload and delete, and SUM(size_bytes) is cheap at this scale.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 1 GiB; admins can bump per-user; quotas higher than disk space are
# operator misconfiguration, not enforced here.
DEFAULT_QUOTA_BYTES = 1024 * 1024 * 1024


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "storage_quota_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=str(DEFAULT_QUOTA_BYTES),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "storage_quota_bytes")
