"""asset read tokens

Revision ID: 0041
Revises: 0040
Create Date: 2026-09-26

Replaces characters/4, which undercounted Polish text and was empty for
PDF, Office and HTML. The rule is in app/token_estimate.py; the SQL backfill
covers kinds whose search blob is the read, others get it on their next write.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("read_tokens", sa.Integer(), nullable=True))
    # Mirrors token_estimate.tokens_for_text: 2.7 characters per token when
    # at least 1% extra UTF-8 bytes per character, 4 otherwise.
    op.execute(
        "UPDATE assets SET read_tokens = CASE "
        "WHEN octet_length(search_content) - length(search_content) "
        ">= 0.01 * length(search_content) "
        "THEN ceil(length(search_content) / 2.7) "
        "ELSE ceil(length(search_content) / 4.0) END "
        "WHERE kind IN ('md_single', 'pdf_doc', 'office_doc') "
        "AND search_content IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("assets", "read_tokens")
