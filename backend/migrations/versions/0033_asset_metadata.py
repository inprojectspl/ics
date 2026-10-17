"""asset metadata columns and the doc type vocabulary

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-26

ADR-0015. Additive only, so the previous image keeps running. Also indexes
content_updated_at for updated_since and "last changed" ordering. The Polish
seed labels are runtime-editable data, not i18n catalogue text.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (key, label_pl, label_en, agent_hint, default_review_days)
DOC_TYPES: tuple[tuple[str, str, str, str, int | None], ...] = (
    (
        "business_goals",
        "Cele biznesowe",
        "Business goals",
        "Read first when scoping work or judging whether a change is worth doing.",
        365,
    ),
    (
        "requirements",
        "Wymagania",
        "Requirements",
        "Read before designing or implementing a feature; it defines what must be delivered.",
        180,
    ),
    (
        "design",
        "Projekt",
        "Design",
        "Read before any design or implementation work that touches the described area.",
        180,
    ),
    (
        "specification",
        "Specyfikacja",
        "Specification",
        "Treat as the binding technical contract when implementing or testing the component.",
        180,
    ),
    (
        "decision",
        "Decyzja",
        "Decision",
        "Check before proposing an alternative; it records why an option was chosen.",
        None,
    ),
    (
        "research",
        "Analiza",
        "Research",
        "Use as background evidence; conclusions may be outdated, verify key facts.",
        365,
    ),
    (
        "report",
        "Raport",
        "Report",
        "Describes a state at a point in time; do not treat it as current guidance.",
        None,
    ),
    (
        "meeting_notes",
        "Notatka ze spotkania",
        "Meeting notes",
        "Look here for agreements and action items; not a source of final decisions.",
        None,
    ),
    (
        "contract",
        "Umowa",
        "Contract",
        "Consult for legal obligations and scope agreed with a client or supplier.",
        None,
    ),
    (
        "offer",
        "Oferta",
        "Offer",
        "Consult for the scope, price and terms proposed to a client.",
        None,
    ),
    (
        "manual",
        "Instrukcja",
        "Manual",
        "Follow when using or configuring the described product or tool.",
        365,
    ),
    (
        "runbook",
        "Procedura operacyjna",
        "Runbook",
        "Follow step by step when operating, deploying or recovering the described system.",
        180,
    ),
    (
        "policy",
        "Polityka",
        "Policy",
        "Obey as a binding rule; flag any task that would conflict with it.",
        365,
    ),
    (
        "presentation",
        "Prezentacja",
        "Presentation",
        "Use as a summary for an audience; check the source documents for details.",
        None,
    ),
)


def upgrade() -> None:
    doc_types = op.create_table(
        "doc_types",
        sa.Column("key", sa.String(32), primary_key=True),
        sa.Column("label_pl", sa.String(100), nullable=False),
        sa.Column("label_en", sa.String(100), nullable=False),
        sa.Column("agent_hint", sa.Text(), nullable=True),
        sa.Column("default_review_days", sa.Integer(), nullable=True),
        sa.Column(
            "properties_schema",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("archived_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.bulk_insert(
        doc_types,
        [
            {
                "key": key,
                "label_pl": label_pl,
                "label_en": label_en,
                "agent_hint": hint,
                "default_review_days": days,
                "position": (i + 1) * 10,
            }
            for i, (key, label_pl, label_en, hint, days) in enumerate(DOC_TYPES)
        ],
    )

    op.add_column("assets", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("assets", sa.Column("summary_source", sa.String(8), nullable=True))
    op.add_column("assets", sa.Column("summary_version", sa.Integer(), nullable=True))
    op.add_column(
        "assets",
        sa.Column("doc_type", sa.String(32), sa.ForeignKey("doc_types.key"), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column(
            "maintainer_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "assets",
        sa.Column("review_due_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column("reviewed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "assets",
        sa.Column(
            "reviewed_by",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("assets", sa.Column("language", sa.String(8), nullable=True))
    op.add_column(
        "assets",
        sa.Column(
            "properties",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_assets_summary_source",
        "assets",
        "summary_source IN ('human','agent')",
    )
    # SET NULL FKs: without the index, deleting a user scans assets.
    op.create_index("ix_assets_maintainer_id", "assets", ["maintainer_id"])
    op.create_index("ix_assets_reviewed_by", "assets", ["reviewed_by"])
    op.create_index(
        "ix_asset_project_doc_type",
        "assets",
        ["project_id", "doc_type"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_assets_review_due_at",
        "assets",
        ["review_due_at"],
        postgresql_where=sa.text("review_due_at IS NOT NULL"),
    )
    op.create_index(
        "ix_asset_content_updated_id",
        "assets",
        [sa.text("content_updated_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.add_column("asset_versions", sa.Column("change_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("asset_versions", "change_note")

    op.drop_index("ix_asset_content_updated_id", table_name="assets")
    op.drop_index("ix_assets_review_due_at", table_name="assets")
    op.drop_index("ix_asset_project_doc_type", table_name="assets")
    op.drop_index("ix_assets_reviewed_by", table_name="assets")
    op.drop_index("ix_assets_maintainer_id", table_name="assets")
    op.drop_constraint("ck_assets_summary_source", "assets", type_="check")
    for column in (
        "properties",
        "language",
        "reviewed_by",
        "reviewed_at",
        "review_due_at",
        "maintainer_id",
        "doc_type",
        "summary_version",
        "summary_source",
        "summary",
    ):
        op.drop_column("assets", column)
    op.drop_table("doc_types")
