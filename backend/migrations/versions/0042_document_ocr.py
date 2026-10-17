"""document ocr

Revision ID: 0042
Revises: 0041
Create Date: 2026-09-28

OCR runs of scanned PDF pages (ADR-0021): one row per document version,
holding the state (queued, running, done, failed), the engine, the dates
and the page counts. The recognized text is stored next to the version.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = postgresql.TIMESTAMP(timezone=True)
    op.create_table(
        "document_ocr",
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column(
            "requested_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("requested_at", ts, server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", ts, nullable=True),
        sa.Column("finished_at", ts, nullable=True),
        sa.Column("heartbeat_at", ts, nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pages_without_text", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pages_with_hidden_text", sa.Integer(), server_default="0", nullable=False),
        sa.Column("replace_hidden_text", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("pages_total", sa.Integer(), nullable=True),
        sa.Column("pages_done", sa.Integer(), nullable=True),
        sa.Column("pages_recognized", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued','running','done','failed')", name="ck_document_ocr_status"
        ),
    )
    op.create_index(
        "ix_document_ocr_active",
        "document_ocr",
        ["status"],
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "ix_document_ocr_requested_by",
        "document_ocr",
        ["requested_by"],
        postgresql_where=sa.text("requested_by IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_document_ocr_requested_by", table_name="document_ocr")
    op.drop_index("ix_document_ocr_active", table_name="document_ocr")
    op.drop_table("document_ocr")
