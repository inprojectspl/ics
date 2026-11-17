"""micro-application short host names

Revision ID: 0051
Revises: 0050
Create Date: 2026-11-17

Each app environment gets a random 8-character public host name
(`<name>.<app host suffix>`) instead of `a-<asset hex>-prod`. Names are
reserved in `microapp_host_names` for good: the table has no foreign key to
the asset, so a purged app keeps its name and nobody else gets it. Existing
environments get their names here; their long hosts keep working.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Unlike constants, the generator may be imported: any name it produces is
# valid, and the database check below pins the format.
from app.config import get_settings
from app.slug import generate_slug

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME_LENGTH = 8


def _alias_labels() -> set[str]:
    """Names whose host is a configured public alias: never handed out."""
    settings = get_settings()
    suffix = f".{settings.microapps_app_host_suffix}"
    return {h.removesuffix(suffix) for h in settings.microapps_alias_map if h.endswith(suffix)}


def upgrade() -> None:
    op.create_table(
        "microapp_host_names",
        sa.Column("name", sa.String(8), primary_key=True),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("asset_id", "environment", name="uq_microapp_host_name_asset_env"),
        sa.CheckConstraint(
            "name ~ '^[abcdefghjkmnpqrstuvwxyz23456789]{8}$'",
            name="ck_microapp_host_name_format",
        ),
    )
    op.add_column("microapp_environments", sa.Column("host_name", sa.String(8), nullable=True))

    conn = op.get_bind()
    taken = _alias_labels()
    envs = conn.execute(
        sa.text(
            "SELECT id, asset_id, environment FROM microapp_environments ORDER BY created_at, id"
        )
    ).all()
    for env_id, asset_id, environment in envs:
        name = generate_slug(NAME_LENGTH)
        while name in taken:
            name = generate_slug(NAME_LENGTH)
        taken.add(name)
        conn.execute(
            sa.text(
                "INSERT INTO microapp_host_names (name, asset_id, environment) "
                "VALUES (:name, :asset_id, :environment)"
            ),
            {"name": name, "asset_id": asset_id, "environment": environment},
        )
        conn.execute(
            sa.text("UPDATE microapp_environments SET host_name = :name WHERE id = :id"),
            {"name": name, "id": env_id},
        )

    op.alter_column("microapp_environments", "host_name", nullable=False)
    op.create_unique_constraint(
        "microapp_environments_host_name_key", "microapp_environments", ["host_name"]
    )
    op.create_foreign_key(
        "microapp_environments_host_name_fkey",
        "microapp_environments",
        "microapp_host_names",
        ["host_name"],
        ["name"],
    )


def downgrade() -> None:
    # Drops the reservations too: names given out before are free again.
    op.drop_constraint(
        "microapp_environments_host_name_fkey", "microapp_environments", type_="foreignkey"
    )
    op.drop_constraint("microapp_environments_host_name_key", "microapp_environments")
    op.drop_column("microapp_environments", "host_name")
    op.drop_table("microapp_host_names")
