"""external references

Revision ID: 0036
Revises: 0035
Create Date: 2026-09-26

ADR-0018. Links assets to tasks in external systems (OpenProject work
packages, Project Standard nodes), maps ICS projects to OpenProject projects
and stores each project's key documents. Additive only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _created_by() -> sa.Column:
    return sa.Column(
        "created_by",
        sa.Uuid(),
        sa.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        postgresql.TIMESTAMP(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "asset_external_refs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("system", sa.String(32), nullable=False),
        sa.Column("entity", sa.String(32), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("external_scope", sa.Text(), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("asset_path", sa.Text(), nullable=True),
        sa.Column("pinned_version", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False),
        _created_by(),
        _created_at(),
        sa.CheckConstraint(
            "system IN ('openproject','project_standard','gitlab','url')",
            name="ck_asset_external_refs_system",
        ),
        sa.CheckConstraint(
            "entity IN ('work_package','project','version','node','merge_request','page')",
            name="ck_asset_external_refs_entity",
        ),
        sa.CheckConstraint(
            "role IN ('context','deliverable','reference')",
            name="ck_asset_external_refs_role",
        ),
        sa.CheckConstraint(
            "origin IN ('manual','agent','integration')",
            name="ck_asset_external_refs_origin",
        ),
    )
    # Leads with asset_id, so it also serves the asset FK.
    op.create_index(
        "uq_asset_external_ref",
        "asset_external_refs",
        [
            "asset_id",
            "system",
            "entity",
            "external_id",
            "role",
            sa.text("coalesce(asset_path, '')"),
        ],
        unique=True,
    )
    op.create_index(
        "ix_asset_external_refs_lookup",
        "asset_external_refs",
        ["system", "entity", "external_id"],
    )
    op.create_index("ix_asset_external_refs_created_by", "asset_external_refs", ["created_by"])

    op.create_table(
        "project_external_refs",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("system", sa.String(32), primary_key=True),
        sa.Column("external_id", sa.Text(), primary_key=True),
        _created_by(),
        _created_at(),
        sa.CheckConstraint(
            "system IN ('openproject','project_standard')",
            name="ck_project_external_refs_system",
        ),
    )
    op.create_index(
        "uq_project_external",
        "project_external_refs",
        ["system", "external_id"],
        unique=True,
    )
    op.create_index("ix_project_external_refs_created_by", "project_external_refs", ["created_by"])

    op.create_table(
        "project_key_documents",
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_project_key_documents_asset", "project_key_documents", ["asset_id"])


def downgrade() -> None:
    op.drop_table("project_key_documents")
    op.drop_table("project_external_refs")
    op.drop_table("asset_external_refs")
