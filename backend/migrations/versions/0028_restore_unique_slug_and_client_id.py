"""restore uniqueness of projects.slug and oauth_clients.client_id

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-24

0019 dropped these unique indexes as duplicates of constraints that never
existed. Concurrent startup seeding could then duplicate client_id rows:
they are merged first (oldest active row kept, tokens and codes moved), and
extras are revoked and renamed rather than deleted because audit_log
references them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MERGE_DUPLICATE_CLIENTS = (
    """
    CREATE TEMP TABLE _oauth_client_dups ON COMMIT DROP AS
    SELECT id, keep_id FROM (
        SELECT id,
               row_number() OVER w AS rn,
               first_value(id) OVER w AS keep_id
        FROM oauth_clients
        WINDOW w AS (
            PARTITION BY client_id
            ORDER BY revoked_at IS NOT NULL, created_at, id
        )
    ) ranked
    WHERE rn > 1
    """,
    """
    UPDATE oauth_refresh_tokens t SET client_id = d.keep_id
    FROM _oauth_client_dups d WHERE t.client_id = d.id
    """,
    """
    UPDATE oauth_auth_codes c SET client_id = d.keep_id
    FROM _oauth_client_dups d WHERE c.client_id = d.id
    """,
    """
    UPDATE oauth_clients c
    SET client_id = left(c.client_id, 100) || '~duplicate~' || left(c.id::text, 8),
        revoked_at = coalesce(c.revoked_at, now())
    FROM _oauth_client_dups d WHERE c.id = d.id
    """,
)


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_slug ON projects (slug)")
    for statement in MERGE_DUPLICATE_CLIENTS:
        op.execute(statement)
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_oauth_clients_client_id ON oauth_clients (client_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_oauth_clients_client_id")
    op.execute("DROP INDEX IF EXISTS ix_projects_slug")
