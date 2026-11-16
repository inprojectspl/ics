"""Include the PS project in a node reference's identity.

Revision ID: 0045
Revises: 0044

OP work packages still use the single configured instance. Legacy missing
PS scopes remain unknown; never invent a project or discard an existing link.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _legacy_index(*, scoped: bool) -> None:
    op.create_index(
        "uq_asset_external_ref",
        "asset_external_refs",
        [
            "asset_id",
            "system",
            "entity",
            "external_id",
            "role",
            sa.text("coalesce(asset_path, '')"),
        ],
        unique=True,
        postgresql_where=sa.text("NOT (system = 'project_standard' AND entity = 'node')")
        if scoped
        else None,
    )


def upgrade() -> None:
    # The old unique index already excludes null/empty-scope collisions.
    op.execute("UPDATE asset_external_refs SET external_scope = NULL WHERE external_scope = ''")
    op.drop_index("uq_asset_external_ref", table_name="asset_external_refs")
    _legacy_index(scoped=True)
    op.create_index(
        "uq_asset_ps_node_ref",
        "asset_external_refs",
        [
            "asset_id",
            "external_id",
            sa.text("coalesce(external_scope, '')"),
            "role",
            sa.text("coalesce(asset_path, '')"),
        ],
        unique=True,
        postgresql_where=sa.text("system = 'project_standard' AND entity = 'node'"),
    )
    # Keep asset lists and FK checks indexed across both partial indexes.
    op.create_index("ix_asset_external_refs_asset", "asset_external_refs", ["asset_id"])


def downgrade() -> None:
    # PostgreSQL rolls the migration back if new cross-project links collide
    # under the old key. A downgrade must not silently drop those links.
    op.drop_index("ix_asset_external_refs_asset", table_name="asset_external_refs")
    op.drop_index("uq_asset_ps_node_ref", table_name="asset_external_refs")
    op.drop_index("uq_asset_external_ref", table_name="asset_external_refs")
    _legacy_index(scoped=False)
