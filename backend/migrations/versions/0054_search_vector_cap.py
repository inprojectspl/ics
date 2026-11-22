"""Cap the content part of the search vector.

Revision ID: 0054
Revises: 0053
Create Date: 2026-11-22

A tsvector holds at most 1 MiB, and a long text with many distinct words
(a large PDF, a transcript) exceeds it: the generated column then fails the
whole write. `ics_search_tsvector` indexes the longest prefix of the text
that fits instead. `search_content` itself stays whole, so phrase checks,
snippets and the content hash still see all of it; only words past the
prefix are not candidates. SET EXPRESSION rewrites the stored vectors.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0054"
down_revision: str | None = "0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_META = (
    "setweight(to_tsvector('public.ics_search', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('public.ics_search', coalesce(slug, '')), 'A') || "
    "setweight(to_tsvector('public.ics_search', coalesce(summary, '')), 'B') || "
    "setweight(to_tsvector('public.ics_search', "
    "coalesce(ics_immutable_array_to_string(tags, ' '), '')), 'B') || "
)
CAPPED = _META + "setweight(ics_search_tsvector(search_content), 'C')"
PREVIOUS = _META + "setweight(to_tsvector('public.ics_search', coalesce(search_content, '')), 'C')"

# Below SHORT characters a vector cannot reach the cap (at most 4 bytes a
# character and about 2.6 vector bytes per text byte), so the common case
# skips the subtransaction of the exception block. LIMIT leaves room for the
# metadata parts of the full vector.
FUNCTION = """
CREATE FUNCTION ics_search_tsvector(content text) RETURNS tsvector
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
DECLARE
    n integer := coalesce(length(content), 0);
    v tsvector;
    size integer;
BEGIN
    IF n <= 65536 THEN
        RETURN to_tsvector('public.ics_search'::regconfig, coalesce(content, ''));
    END IF;
    LOOP
        BEGIN
            v := to_tsvector('public.ics_search'::regconfig, left(content, n));
            size := pg_column_size(v);
            IF size <= 900000 THEN
                RETURN v;
            END IF;
            -- A vector grows at most linearly with its text: aim under the cap.
            n := least(n * 3 / 4, (n::bigint * 850000 / size)::integer);
        EXCEPTION WHEN program_limit_exceeded THEN
            -- Past 1 MiB, by an unknown amount.
            n := n / 2;
        END;
    END LOOP;
END
$$
"""


def upgrade() -> None:
    op.execute(FUNCTION)
    op.execute(f"ALTER TABLE assets ALTER COLUMN search_tsv SET EXPRESSION AS ({CAPPED})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE assets ALTER COLUMN search_tsv SET EXPRESSION AS ({PREVIOUS})")
    op.execute("DROP FUNCTION ics_search_tsvector(text)")
