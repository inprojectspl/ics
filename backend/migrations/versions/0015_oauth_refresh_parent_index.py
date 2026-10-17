"""index on oauth_refresh_tokens.parent_id

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-16

revoke_refresh_chain walks down by parent_id; without this index each step
is a full scan. Partial on parent_id IS NOT NULL only: reuse detection must
also find revoked children to reach their live descendants, so a
revoked_at IS NULL predicate would leave live tokens after a reuse attack.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_refresh_tokens_parent_id "
        "ON oauth_refresh_tokens (parent_id) "
        "WHERE parent_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_oauth_refresh_tokens_parent_id")
