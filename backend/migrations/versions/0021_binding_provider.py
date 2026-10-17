"""binding provider column

Revision ID: 0021
Revises: 0020
Create Date: 2026-05-20

provider and webhook_url are both NULL or both set (CHECK constraint, a
safeguard against writes that bypass DTO validation). Existing rows with a
webhook are backfilled with 'google_chat', the only provider.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "gitlab_bindings",
        sa.Column("provider", sa.String(length=32), nullable=True),
    )
    # Backfilled regardless of the chat.googleapis.com allowlist: route
    # validation catches an off-domain URL on the next PATCH.
    op.execute(
        "UPDATE gitlab_bindings SET provider = 'google_chat' "
        "WHERE webhook_url IS NOT NULL AND webhook_url <> ''"
    )
    op.create_check_constraint(
        "ck_gitlab_bindings_webhook_provider_pair",
        "gitlab_bindings",
        "(webhook_url IS NULL AND provider IS NULL) OR "
        "(webhook_url IS NOT NULL AND provider IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_gitlab_bindings_webhook_provider_pair",
        "gitlab_bindings",
        type_="check",
    )
    op.drop_column("gitlab_bindings", "provider")
