"""Accent-insensitive document search, including document slugs.

Revision ID: 0044
Revises: 0043

SET EXPRESSION rewrites existing vectors and rebuilds their GIN index.
The configuration is versioned with this migration: changing a dictionary
requires rebuilding stored vectors, not just REINDEX.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WEIGHTED = (
    "setweight(to_tsvector('public.ics_search', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('public.ics_search', coalesce(slug, '')), 'A') || "
    "setweight(to_tsvector('public.ics_search', coalesce(summary, '')), 'B') || "
    "setweight(to_tsvector('public.ics_search', "
    "coalesce(ics_immutable_array_to_string(tags, ' '), '')), 'B') || "
    "setweight(to_tsvector('public.ics_search', coalesce(search_content, '')), 'C')"
)
PREVIOUS = (
    "setweight(to_tsvector('simple', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('simple', coalesce(summary, '')), 'A') || "
    "setweight(to_tsvector('simple', "
    "coalesce(ics_immutable_array_to_string(tags, ' '), '')), 'B') || "
    "setweight(to_tsvector('simple', coalesce(search_content, '')), 'C')"
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA public")
    op.execute("CREATE TEXT SEARCH CONFIGURATION public.ics_search (COPY = pg_catalog.simple)")
    op.execute(
        "ALTER TEXT SEARCH CONFIGURATION public.ics_search "
        "ALTER MAPPING FOR hword, hword_part, word "
        "WITH public.unaccent, pg_catalog.simple"
    )
    op.execute(f"ALTER TABLE assets ALTER COLUMN search_tsv SET EXPRESSION AS ({WEIGHTED})")


def downgrade() -> None:
    op.execute(f"ALTER TABLE assets ALTER COLUMN search_tsv SET EXPRESSION AS ({PREVIOUS})")
    op.execute("DROP TEXT SEARCH CONFIGURATION public.ics_search")
