"""projects, project_members, asset_shares + assets.project_id

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-14

Existing assets get project_id = NULL and stay in the personal vault. The
partial unique index on (project_id) WHERE role='owner' allows at most one
owner; the application keeps at least one inside transactions.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(32), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_projects_slug", "projects", ["slug"], unique=True)
    op.create_index("ix_projects_created_by", "projects", ["created_by"])

    op.create_table(
        "project_members",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "invited_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "invited_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("accepted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        sa.CheckConstraint(
            "role IN ('owner','editor','viewer')",
            name="ck_project_members_role",
        ),
    )
    op.create_index("ix_project_members_project", "project_members", ["project_id"])
    op.create_index("ix_project_members_user", "project_members", ["user_id"])
    # Partial unique: max one owner per project. The application enforces min one.
    op.execute(
        "CREATE UNIQUE INDEX uq_project_members_one_owner "
        "ON project_members (project_id) WHERE role = 'owner'"
    )

    op.create_table(
        "asset_shares",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "asset_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column(
            "granted_by",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "granted_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("asset_id", "user_id", name="uq_asset_shares_asset_user"),
        sa.CheckConstraint(
            "role IN ('editor','viewer')",
            name="ck_asset_shares_role",
        ),
    )
    op.create_index("ix_asset_shares_asset", "asset_shares", ["asset_id"])
    op.create_index("ix_asset_shares_user", "asset_shares", ["user_id"])

    op.add_column(
        "assets",
        sa.Column(
            "project_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_assets_project", "assets", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_assets_project", table_name="assets")
    op.drop_column("assets", "project_id")

    op.drop_index("ix_asset_shares_user", table_name="asset_shares")
    op.drop_index("ix_asset_shares_asset", table_name="asset_shares")
    op.drop_table("asset_shares")

    op.execute("DROP INDEX IF EXISTS uq_project_members_one_owner")
    op.drop_index("ix_project_members_user", table_name="project_members")
    op.drop_index("ix_project_members_project", table_name="project_members")
    op.drop_table("project_members")

    op.drop_index("ix_projects_created_by", table_name="projects")
    op.drop_index("ix_projects_slug", table_name="projects")
    op.drop_table("projects")
