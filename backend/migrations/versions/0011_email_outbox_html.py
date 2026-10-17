"""email_outbox html body

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-13

All outgoing emails now get an HTML version alongside the plain text
(`multipart/alternative`). The old `body` column stays as the text-only
fallback; the new `body_html` is optional, and when it is NULL the mail
client sees only plain text.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "email_outbox",
        sa.Column("body_html", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("email_outbox", "body_html")
