"""per-user html bundle size limit

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-07

Same pattern as storage_quota_bytes (0005), but caps a single upload, not
the sum; the quota still applies independently.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match app.constants.DEFAULT_BUNDLE_MAX_BYTES. Migrations do not import
# application code, so an old script cannot change meaning after the constant
# is refactored.
DEFAULT_BUNDLE_MAX_BYTES = 5 * 1024 * 1024


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "bundle_max_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=str(DEFAULT_BUNDLE_MAX_BYTES),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "bundle_max_bytes")
