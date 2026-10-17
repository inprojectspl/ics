"""asset relations graph table

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-26

ADR-0016. One edge table, each edge stored once in its canonical direction.
Additive only: the previous image never touches this table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asset_relations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("target_path", sa.Text(), nullable=True),
        sa.Column("target_anchor", sa.Text(), nullable=True),
        sa.Column("target_version", sa.Integer(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column(
            "created_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "relation_type IN ('derived_from','supersedes','depends_on','part_of',"
            "'references','relates_to','duplicates','contradicts')",
            name="ck_asset_relations_type",
        ),
        sa.CheckConstraint(
            "origin IN ('manual','agent','extracted','integration')",
            name="ck_asset_relations_origin",
        ),
        sa.CheckConstraint(
            "source_asset_id <> target_asset_id",
            name="ck_asset_relations_not_self",
        ),
    )
    # Leads with the source, so it also serves the source-side FK cascade.
    op.create_index(
        "uq_asset_relation",
        "asset_relations",
        [
            "source_asset_id",
            "target_asset_id",
            "relation_type",
            sa.text("coalesce(source_path, '')"),
            sa.text("coalesce(target_path, '')"),
            sa.text("coalesce(target_anchor, '')"),
        ],
        unique=True,
    )
    op.create_index(
        "ix_asset_relations_target",
        "asset_relations",
        ["target_asset_id", "relation_type"],
    )
    op.create_index("ix_asset_relations_created_by", "asset_relations", ["created_by"])


def downgrade() -> None:
    op.drop_table("asset_relations")
