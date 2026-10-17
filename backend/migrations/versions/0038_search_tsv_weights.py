"""weighted search vector

Revision ID: 0038
Revises: 0037
Create Date: 2026-09-26

ADR-0015, section 5. Weights: title and summary A, tags B, content C.
A generated column needs IMMUTABLE functions and array_to_string is STABLE,
hence ics_immutable_array_to_string (safe: no setting or locale dependence).
SET EXPRESSION (PostgreSQL 17+) rewrites the table and rebuilds the index.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WEIGHTED = (
    "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(summary, '')), 'A') || "
    "setweight(to_tsvector('simple', "
    "coalesce(ics_immutable_array_to_string(tags, ' '), '')), 'B') || "
    "setweight(to_tsvector('simple', coalesce(search_content, '')), 'C')"
)
PLAIN = "to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(search_content, ''))"


def upgrade() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION ics_immutable_array_to_string(text[], text) "
        "RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE "
        "AS $$ SELECT array_to_string($1, $2) $$"
    )
    op.execute(f"ALTER TABLE assets ALTER COLUMN search_tsv SET EXPRESSION AS ({WEIGHTED})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE assets ALTER COLUMN search_tsv SET EXPRESSION AS ({PLAIN})")
    op.execute("DROP FUNCTION IF EXISTS ics_immutable_array_to_string(text[], text)")
