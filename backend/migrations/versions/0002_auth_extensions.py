"""auth extensions: password auth + outbox + attempts

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-11

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("auth_method", sa.String(32), nullable=False, server_default="google_sso"),
    )
    op.add_column("users", sa.Column("password_hash", sa.Text()))
    op.add_column("users", sa.Column("email_verified_at", postgresql.TIMESTAMP(timezone=True)))
    op.add_column("users", sa.Column("locked_until", postgresql.TIMESTAMP(timezone=True)))

    op.create_table(
        "auth_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("ip_hash", sa.String(64)),
        sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "timestamp",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_auth_attempts_email", "auth_attempts", ["email"])
    op.create_index("ix_auth_attempts_timestamp", "auth_attempts", ["timestamp"])

    op.create_table(
        "email_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("to_email", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("sent_at", postgresql.TIMESTAMP(timezone=True)),
    )
    op.create_index("ix_email_outbox_to_email", "email_outbox", ["to_email"])
    op.create_index("ix_email_outbox_created_at", "email_outbox", ["created_at"])


def downgrade() -> None:
    op.drop_table("email_outbox")
    op.drop_table("auth_attempts")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "auth_method")
