"""OAuth 2.1 Authorization Server tables (MCP-spec 2025-11-25)

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-15

Clients, single-use auth codes, rotating refresh tokens (reuse detection via
parent_id) and a JTI blacklist. Access JWTs are stateless (RS256, /jwks.json)
and not stored. audit_log gains client_id and transport.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # oauth_clients
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", sa.String(128), nullable=False),
        sa.Column("client_secret_hash", sa.Text(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("client_type", sa.String(16), nullable=False),
        sa.Column("redirect_uris", sa.dialects.postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column(
            "allowed_scopes",
            sa.dialects.postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{ics}",
        ),
        sa.Column("allowed_audiences", sa.dialects.postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column(
            "owner_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_dynamic", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "client_type IN ('public','confidential')",
            name="ck_oauth_clients_type",
        ),
    )
    op.create_index("ix_oauth_clients_client_id", "oauth_clients", ["client_id"], unique=True)
    op.execute(
        "CREATE INDEX ix_oauth_clients_active "
        "ON oauth_clients (revoked_at) WHERE revoked_at IS NULL"
    )

    # oauth_auth_codes
    op.create_table(
        "oauth_auth_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column(
            "client_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("scopes", sa.dialects.postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("code_challenge_method", sa.String(8), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.CheckConstraint(
            "code_challenge_method = 'S256'",
            name="ck_oauth_auth_codes_pkce_method",
        ),
    )
    op.create_index("ix_oauth_auth_codes_client", "oauth_auth_codes", ["client_id"])
    op.create_index("ix_oauth_auth_codes_user", "oauth_auth_codes", ["user_id"])
    op.create_index("ix_oauth_auth_codes_expires", "oauth_auth_codes", ["expires_at"])
    op.execute(
        "CREATE INDEX ix_oauth_auth_codes_unused "
        "ON oauth_auth_codes (code_hash) WHERE used_at IS NULL"
    )

    # oauth_refresh_tokens
    op.create_table(
        "oauth_refresh_tokens",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "client_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("oauth_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scopes", sa.dialects.postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("jwt_id", sa.String(64), nullable=False),
        sa.Column(
            "parent_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("oauth_refresh_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("rotated_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_oauth_refresh_token_hash", "oauth_refresh_tokens", ["token_hash"], unique=True
    )
    op.create_index("ix_oauth_refresh_client", "oauth_refresh_tokens", ["client_id"])
    op.create_index("ix_oauth_refresh_user", "oauth_refresh_tokens", ["user_id"])
    op.execute(
        "CREATE INDEX ix_oauth_refresh_active "
        "ON oauth_refresh_tokens (user_id, client_id) WHERE revoked_at IS NULL"
    )

    # oauth_jti_blacklist
    op.create_table(
        "oauth_jti_blacklist",
        sa.Column("jti", sa.String(64), primary_key=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "revoked_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_oauth_jti_expires", "oauth_jti_blacklist", ["expires_at"])

    # audit_log: client_id + transport
    op.add_column(
        "audit_log",
        sa.Column(
            "client_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("oauth_clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "audit_log",
        sa.Column("transport", sa.String(16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_log", "transport")
    op.drop_column("audit_log", "client_id")

    op.drop_index("ix_oauth_jti_expires", table_name="oauth_jti_blacklist")
    op.drop_table("oauth_jti_blacklist")

    op.execute("DROP INDEX IF EXISTS ix_oauth_refresh_active")
    op.drop_index("ix_oauth_refresh_user", table_name="oauth_refresh_tokens")
    op.drop_index("ix_oauth_refresh_client", table_name="oauth_refresh_tokens")
    op.drop_index("ix_oauth_refresh_token_hash", table_name="oauth_refresh_tokens")
    op.drop_table("oauth_refresh_tokens")

    op.execute("DROP INDEX IF EXISTS ix_oauth_auth_codes_unused")
    op.drop_index("ix_oauth_auth_codes_expires", table_name="oauth_auth_codes")
    op.drop_index("ix_oauth_auth_codes_user", table_name="oauth_auth_codes")
    op.drop_index("ix_oauth_auth_codes_client", table_name="oauth_auth_codes")
    op.drop_table("oauth_auth_codes")

    op.execute("DROP INDEX IF EXISTS ix_oauth_clients_active")
    op.drop_index("ix_oauth_clients_client_id", table_name="oauth_clients")
    op.drop_table("oauth_clients")
