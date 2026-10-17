"""cdn allowlist

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-13

Unioned with ICS_TRUSTED_CDN_HOSTS at every scan; the env value is the
baseline that survives DB resets. Hosts are stored lowercase and matched
exactly; wildcard subdomains are deliberately unsupported.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cdn_allowlist",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("host", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "added_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_cdn_allowlist_host", "cdn_allowlist", ["host"])


def downgrade() -> None:
    op.drop_index("ix_cdn_allowlist_host", table_name="cdn_allowlist")
    op.drop_table("cdn_allowlist")
