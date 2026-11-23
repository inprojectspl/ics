"""google sheets links of micro-applications

Revision ID: 0055
Revises: 0054
Create Date: 2026-11-22

A person's Google grant, the link of an app collection to a sheet tab, the
base of the three-way comparison and the sync operations (ADR-0031), and
the per-owner cap on the rows a link may sync; the realtime counts of
micro-applications the broker reports (ADR-0032), which drive automatic
syncs.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from app.constants import DEFAULT_SHEET_MAX_ROWS

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.TIMESTAMP(timezone=True)


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", TS, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    for name in ("realtime_sockets", "realtime_people"):
        op.add_column(
            "microapp_stats", sa.Column(name, sa.Integer(), server_default="0", nullable=False)
        )
    op.add_column(
        "users",
        sa.Column(
            "sheet_max_rows",
            sa.Integer(),
            server_default=str(DEFAULT_SHEET_MAX_ROWS),
            nullable=False,
        ),
    )
    op.create_table(
        "google_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("refresh_token_enc", sa.Text(), nullable=False),
        *_stamps(),
    )
    op.create_table(
        "sheet_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("collection", sa.String(64), nullable=False),
        sa.Column("spreadsheet_id", sa.String(128), nullable=False, unique=True),
        sa.Column("sheet_title", sa.String(100), nullable=False),
        sa.Column("key_field", sa.String(64)),
        sa.Column("columns", JSONB(), nullable=False),
        sa.Column("account_mode", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("paused", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("auto_sync", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("app_changed_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("auto_checked_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("auto_next_at", sa.TIMESTAMP(timezone=True)),
        sa.Column("auto_sheet_hash", sa.String(64)),
        sa.Column("auto_error", sa.String(64)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_stamps(),
        sa.CheckConstraint(
            "account_mode IN ('owner_account', 'per_user')", name="ck_sheet_links_account_mode"
        ),
    )
    op.create_table(
        "sheet_base",
        sa.Column(
            "link_id",
            sa.Uuid(),
            sa.ForeignKey("sheet_links.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("record_id", sa.Uuid(), primary_key=True),
        sa.Column("values", JSONB(), nullable=False),
        sa.Column("row", sa.Integer()),
    )
    op.create_table(
        "sheet_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "link_id",
            sa.Uuid(),
            sa.ForeignKey("sheet_links.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("link_revision", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("google_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("google_status", sa.String(16), nullable=False),
        sa.Column("summary", JSONB(), server_default="{}", nullable=False),
        sa.Column("preview", JSONB(), nullable=False),
        sa.Column("decisions", JSONB()),
        sa.Column("export", JSONB()),
        sa.Column("result", JSONB()),
        sa.Column("error", sa.String(64)),
        sa.Column("auto", sa.Boolean(), server_default="false", nullable=False),
        *_stamps(),
        sa.CheckConstraint(
            "state IN ('previewed', 'applying', 'applied', 'stale', 'superseded', 'failed')",
            name="ck_sheet_operations_state",
        ),
        sa.CheckConstraint(
            "google_status IN ('none', 'pending', 'confirmed', 'uncertain', 'failed')",
            name="ck_sheet_operations_google_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("sheet_operations")
    op.drop_table("sheet_base")
    op.drop_table("sheet_links")
    op.drop_table("google_grants")
    op.drop_column("users", "sheet_max_rows")
    op.drop_column("microapp_stats", "realtime_people")
    op.drop_column("microapp_stats", "realtime_sockets")
