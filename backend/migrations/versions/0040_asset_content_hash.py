"""asset content hash

Revision ID: 0040
Revises: 0039
Create Date: 2026-09-26

Duplicate suggestions hashed every document's normalised text on each
listing. A STORED generated column; no index, since the comparison runs
inside one project CTE. convert_to is STABLE, hence the IMMUTABLE wrapper
ics_content_hash (safe: constant target encoding).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION ics_content_hash(text) "
        "RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE "
        "AS $$ SELECT CASE WHEN n <> '' "
        "THEN encode(sha256(convert_to(n, 'UTF8')), 'hex') END "
        r"FROM (SELECT lower(btrim(regexp_replace($1, '\s+', ' ', 'g'))) AS n) AS s $$"
    )
    op.execute(
        "ALTER TABLE assets ADD COLUMN content_hash text "
        "GENERATED ALWAYS AS (ics_content_hash(search_content)) STORED"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE assets DROP COLUMN IF EXISTS content_hash")
    op.execute("DROP FUNCTION IF EXISTS ics_content_hash(text)")
