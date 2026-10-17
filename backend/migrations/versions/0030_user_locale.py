"""per-user locale for backend-rendered text

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-24

E-mails, chat cards and backend-rendered pages are available in Polish and
English (ADR-0011). The column holds the user's choice; NULL means the
request's Accept-Language decides, so existing rows need no backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale")
