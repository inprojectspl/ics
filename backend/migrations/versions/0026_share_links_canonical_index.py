"""partial index for the canonical-share lookup on /doc

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-21

pick_canonical_share runs on /doc for every owner. The partial index holds
only links that can win (not revoked, no view budget). expires_at stays out:
a time-dependent predicate is not immutable, so it cannot be indexed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_share_links_canonical "
        "ON share_links (asset_id) "
        "WHERE revoked_at IS NULL AND max_views IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_share_links_canonical")
