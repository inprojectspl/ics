"""asset search tsvector generated column + index

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-11

A STORED generated column, not an expression index, so the query, ranking
and index read one expression. The title is included so html_bundle assets
(search_content NULL, see 0006) are findable. Rewrites the table under
AccessExclusiveLock: seconds at the current scale, but a much larger table
would need CONCURRENTLY in an autocommit block.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE assets ADD COLUMN search_tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', "
        "coalesce(title, '') || ' ' || coalesce(search_content, ''))) STORED"
    )
    op.execute(
        "CREATE INDEX ix_assets_search_tsv "
        "ON assets USING gin (search_tsv) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_assets_search_tsv")
    op.execute("ALTER TABLE assets DROP COLUMN IF EXISTS search_tsv")
