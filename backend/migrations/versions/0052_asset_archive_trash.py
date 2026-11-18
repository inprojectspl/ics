"""asset archive and trash

Revision ID: 0052
Revises: 0051
Create Date: 2026-11-18

An archived asset stays usable but leaves lists and search (`archived_at`).
A deleted asset is in the trash (`deleted_at`, now with `deleted_by`) until
`purge_at`, when the purge job removes it for good (ADR-0029). Assets
deleted before the trash existed get the full retention period from now,
so nobody loses a document on the day this ships.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The default of ICS_TRASH_RETENTION_DAYS; a migration does not read settings.
RETENTION_DAYS = 30


def upgrade() -> None:
    op.add_column("assets", sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True))
    for column in ("archived_by", "deleted_by"):
        op.add_column(
            "assets",
            sa.Column(
                column,
                sa.Uuid(),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    op.add_column("assets", sa.Column("purge_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.execute(
        "UPDATE assets SET purge_at = now() + make_interval(days => "
        f"{RETENTION_DAYS}) WHERE deleted_at IS NOT NULL"
    )
    in_trash = sa.text("deleted_at IS NOT NULL")
    op.create_index("ix_assets_purge_at", "assets", ["purge_at"], postgresql_where=in_trash)
    for statement in (
        "CREATE INDEX ix_assets_trash_owner ON assets (owner_id, deleted_at DESC) "
        "WHERE deleted_at IS NOT NULL",
        "CREATE INDEX ix_assets_trash_project ON assets (project_id, deleted_at DESC) "
        "WHERE deleted_at IS NOT NULL",
        "CREATE INDEX ix_assets_archived_owner ON assets (owner_id, updated_at DESC) "
        "WHERE archived_at IS NOT NULL AND deleted_at IS NULL",
    ):
        op.execute(statement)


_INDEXES = ("ix_assets_archived_owner", "ix_assets_trash_project", "ix_assets_trash_owner")


def downgrade() -> None:
    for name in _INDEXES:
        op.drop_index(name, table_name="assets")
    op.drop_index("ix_assets_purge_at", table_name="assets")
    for column in ("purge_at", "deleted_by", "archived_by", "archived_at"):
        op.drop_column("assets", column)
