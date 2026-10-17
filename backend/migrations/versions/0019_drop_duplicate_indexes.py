"""drop duplicate indexes: UNIQUE constraint already provides B-tree

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-17

`unique=True, index=True` created a second B-tree identical to the UNIQUE
one, doubling write cost. The models drop `index=True` to match.
Note: 0012/0013 used unique indexes, not constraints; 0028 restores those.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DROP = [
    "ix_users_email",
    "ix_projects_slug",
    "ix_assets_slug",
    "ix_share_links_token",
    "ix_cdn_allowlist_host",
    "ix_oauth_clients_client_id",
    "ix_oauth_refresh_tokens_token_hash",
]


def upgrade() -> None:
    for name in _DROP:
        op.execute(f"DROP INDEX IF EXISTS {name}")


def downgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_email ON users (email)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_slug ON projects (slug)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_assets_slug ON assets (slug)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_share_links_token ON share_links (token)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_cdn_allowlist_host ON cdn_allowlist (host)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_oauth_clients_client_id ON oauth_clients (client_id)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_oauth_refresh_tokens_token_hash "
        "ON oauth_refresh_tokens (token_hash)"
    )
