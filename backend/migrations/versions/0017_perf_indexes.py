"""perf indexes: audit_log.client_id, auth_attempts composite, users hot paths

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-17

audit_log.client_id: the SET NULL cascade on oauth_clients deletes scanned
the table. auth_attempts (email, timestamp) WHERE NOT succeeded serves the
failed-login count. users.last_login_at / locked_until serve the admin list.
All partial because most rows are NULL or irrelevant there.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_log_client_id "
        "ON audit_log (client_id) WHERE client_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_auth_attempts_email_failed_ts "
        "ON auth_attempts (email, timestamp) WHERE succeeded = false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_last_login_at "
        "ON users (last_login_at) WHERE last_login_at IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_locked_until "
        "ON users (locked_until) WHERE locked_until IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_locked_until")
    op.execute("DROP INDEX IF EXISTS ix_users_last_login_at")
    op.execute("DROP INDEX IF EXISTS ix_auth_attempts_email_failed_ts")
    op.execute("DROP INDEX IF EXISTS ix_audit_log_client_id")
