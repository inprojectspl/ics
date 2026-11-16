"""user micro-application data limit

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-13

Per-user cap on the data of all micro-applications the user owns, set by an
admin like `storage_quota_bytes` and `bundle_max_bytes`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_MICROAPP_DATA_MAX_BYTES = 100 * 1024 * 1024


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "microapp_data_max_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=str(DEFAULT_MICROAPP_DATA_MAX_BYTES),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "microapp_data_max_bytes")
