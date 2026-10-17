"""binding webhook url

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-12

Per-binding webhook URL fired on sync success/failure. Pasted directly
from Google Chat / Slack / Mattermost; they all accept the same minimal
`{"text": "..."}` shape, so we don't need a per-platform adapter.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gitlab_bindings",
        sa.Column("webhook_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gitlab_bindings", "webhook_url")
