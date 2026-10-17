"""point html-json v1 version rows at the v1 tree

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-24

The JSON bundle upload stored assets/<slug> instead of assets/<slug>/v1 as
the v1 prefix, so restoring it copied every version. Downgrade is a no-op:
the old value was wrong.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FIX_SQL = """
UPDATE asset_versions AS v
SET storage_prefix = a.storage_prefix || '/v1'
FROM assets AS a
WHERE v.asset_id = a.id
  AND v.version = 1
  AND v.storage_prefix = a.storage_prefix
"""


def upgrade() -> None:
    op.execute(FIX_SQL)


def downgrade() -> None:
    pass
