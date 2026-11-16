"""share link app permissions

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-12

A share link of a micro-application names the app permissions its holders
get (a subset of the release's declared permissions). NULL for documents.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "share_links", sa.Column("app_permissions", postgresql.ARRAY(sa.String()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("share_links", "app_permissions")
