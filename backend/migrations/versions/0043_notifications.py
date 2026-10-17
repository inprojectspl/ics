"""notifications

Revision ID: 0043
Revises: 0042
Create Date: 2026-09-28

Notification configuration (ADR-0023): what a user watches, their channel
preferences and their browser push devices. The notifications themselves are
kept in Redis.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = postgresql.TIMESTAMP(timezone=True)
    op.create_table(
        "watches",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("num_nonnulls(asset_id, project_id) = 1", name="ck_watches_one_target"),
        sa.CheckConstraint(
            "(asset_id IS NOT NULL AND level IN ('watch','mute'))"
            " OR (project_id IS NOT NULL AND level IN ('new','all'))",
            name="ck_watches_level",
        ),
    )
    op.create_index(
        "uq_watches_user_asset",
        "watches",
        ["user_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("asset_id IS NOT NULL"),
    )
    op.create_index(
        "uq_watches_user_project",
        "watches",
        ["user_id", "project_id"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )
    op.create_index("ix_watches_user_created", "watches", ["user_id", "created_at"])
    op.create_index(
        "ix_watches_asset",
        "watches",
        ["asset_id"],
        postgresql_where=sa.text("asset_id IS NOT NULL"),
    )
    op.create_index(
        "ix_watches_project",
        "watches",
        ["project_id"],
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )

    op.create_table(
        "notification_preferences",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("watch_own_assets", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("email_mode", sa.String(8), server_default="off", nullable=False),
        sa.Column("events", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("chat_webhook_enc", sa.Text(), nullable=True),
        sa.Column("chat_space", sa.String(64), nullable=True),
        sa.Column("chat_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("chat_error_code", sa.String(32), nullable=True),
        sa.Column("updated_at", ts, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "email_mode IN ('off','batched','daily')", name="ck_notification_prefs_email_mode"
        ),
    )

    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("endpoint", sa.Text(), nullable=False, unique=True),
        sa.Column("p256dh", sa.String(128), nullable=False),
        sa.Column("auth", sa.String(64), nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.Column("last_success_at", ts, nullable=True),
    )
    op.create_index("ix_push_subscriptions_user", "push_subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_push_subscriptions_user", table_name="push_subscriptions")
    op.drop_table("push_subscriptions")
    op.drop_table("notification_preferences")
    op.drop_index("ix_watches_project", table_name="watches")
    op.drop_index("ix_watches_asset", table_name="watches")
    op.drop_index("ix_watches_user_created", table_name="watches")
    op.drop_index("uq_watches_user_project", table_name="watches")
    op.drop_index("uq_watches_user_asset", table_name="watches")
    op.drop_table("watches")
