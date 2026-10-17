"""per-user auto-accept for critical html bundles

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-07

For authors whose tooling injects eval() into every build. Trust is per
author, not per bundle. The scan still runs; an automatic bypass is stored
like a manual one (with its reason), so revoke works unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "html_autobypass",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "html_autobypass")
