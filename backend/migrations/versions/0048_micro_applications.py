"""micro-applications

Revision ID: 0048
Revises: 0047
Create Date: 2026-11-12

Platform records of the `micro_application` asset kind: environments with
their desired state and active release, database bindings, releases, plans,
durable operations, business permission grants, measurements, logs and
cleanup orders. A trigger turns every deleted binding into a cleanup order,
so dropping the per-asset schema and roles survives any cascade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0048"
down_revision: str | None = "0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    ts = postgresql.TIMESTAMP(timezone=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "microapp_environments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("asset_hex", sa.String(32), nullable=False, unique=True),
        sa.Column("desired_state", sa.String(16), server_default="enabled", nullable=False),
        sa.Column("active_release_id", sa.Uuid(), nullable=True),
        sa.Column("schema_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("applied_model", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("data_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("policy_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("control_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("suspended_at", ts, nullable=True),
        sa.Column(
            "suspended_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", ts, server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("asset_id", "environment", name="uq_microapp_env_asset_env"),
        sa.CheckConstraint(
            "desired_state IN ('enabled','suspended')", name="ck_microapp_env_desired"
        ),
    )

    op.create_table(
        "microapp_releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "asset_version_id",
            sa.Uuid(),
            sa.ForeignKey("asset_versions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(80), nullable=False),
        sa.Column("manifest", jsonb, nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("profile", sa.String(64), nullable=False),
        sa.Column("schema_min", sa.Integer(), nullable=False),
        sa.Column("schema_max", sa.Integer(), nullable=False),
        sa.Column("target_schema_version", sa.Integer(), nullable=False),
        sa.Column("validation", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("status", sa.String(16), server_default="candidate", nullable=False),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.Column("activated_at", ts, nullable=True),
        sa.CheckConstraint(
            "status IN ('candidate','active','superseded','failed')",
            name="ck_microapp_release_status",
        ),
    )
    op.create_index("ix_microapp_releases_asset_id", "microapp_releases", ["asset_id"])
    op.create_foreign_key(
        "microapp_environments_active_release_id_fkey",
        "microapp_environments",
        "microapp_releases",
        ["active_release_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "microapp_schema_bindings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "environment_id",
            sa.Uuid(),
            sa.ForeignKey("microapp_environments.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("database", sa.String(63), nullable=False),
        sa.Column("schema_name", sa.String(63), nullable=False),
        sa.Column("owner_role", sa.String(63), nullable=False),
        sa.Column("runtime_role", sa.String(63), nullable=False),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("provisioned_at", ts, nullable=True),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "microapp_plans",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("digest", sa.String(80), nullable=False),
        sa.Column("storage_prefix", sa.Text(), nullable=False),
        sa.Column("files", jsonb, nullable=False),
        sa.Column("manifest", jsonb, nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("expected_generation", sa.Integer(), nullable=False),
        sa.Column("migration", jsonb, nullable=False),
        sa.Column("diagnostics", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("expires_at", ts, nullable=False),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("action IN ('create','update')", name="ck_microapp_plan_action"),
    )
    op.create_index("ix_microapp_plans_user_id", "microapp_plans", ["user_id"])
    # The sweeper drops expired plans every 30 s.
    op.create_index("ix_microapp_plans_expires_at", "microapp_plans", ["expires_at"])

    op.create_table(
        "microapp_operations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "plan_id",
            sa.String(40),
            sa.ForeignKey("microapp_plans.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("step", sa.String(32), server_default="accepted", nullable=False),
        sa.Column("steps", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column(
            "asset_version_id",
            sa.Uuid(),
            sa.ForeignKey("asset_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "release_id",
            sa.Uuid(),
            sa.ForeignKey("microapp_releases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("result", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_until", ts, nullable=True),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", ts, server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", ts, nullable=True),
        sa.UniqueConstraint("actor_id", "idempotency_key", name="uq_microapp_op_idempotency"),
        sa.CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_microapp_op_status",
        ),
    )
    op.create_index("ix_microapp_operations_asset_id", "microapp_operations", ["asset_id"])
    # Running operations keep their plan; a dropped plan nulls its operations.
    op.create_index("ix_microapp_operations_plan_id", "microapp_operations", ["plan_id"])

    op.create_table(
        "microapp_grants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("permission", sa.String(120), nullable=False),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "created_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("num_nonnulls(user_id, project_id) = 1", name="ck_microapp_grant_one"),
        sa.UniqueConstraint(
            "asset_id",
            "environment",
            "permission",
            "user_id",
            "project_id",
            name="uq_microapp_grant",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index("ix_microapp_grants_asset_id", "microapp_grants", ["asset_id"])

    op.create_table(
        "microapp_stats",
        sa.Column(
            "environment_id",
            sa.Uuid(),
            sa.ForeignKey("microapp_environments.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("runtime_state", sa.String(16), nullable=True),
        sa.Column("runtime_sampled_at", ts, nullable=True),
        sa.Column("broker_incarnation", sa.String(64), nullable=True),
        sa.Column("inflight", sa.Integer(), server_default="0", nullable=False),
        sa.Column("queued", sa.Integer(), server_default="0", nullable=False),
        sa.Column("open_connections", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_used_at", ts, nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column("last_error_at", ts, nullable=True),
        sa.Column("breaker_open_until", ts, nullable=True),
        sa.Column("db_bytes", sa.BigInteger(), nullable=True),
        sa.Column("db_rows_estimate", sa.BigInteger(), nullable=True),
        sa.Column("db_tables", sa.Integer(), nullable=True),
        sa.Column("db_sampled_at", ts, nullable=True),
    )

    op.create_table(
        "microapp_cleanup_orders",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("database", sa.String(63), nullable=False),
        sa.Column("schema_name", sa.String(63), nullable=False),
        sa.Column("owner_role", sa.String(63), nullable=False),
        sa.Column("runtime_role", sa.String(63), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", ts, server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", ts, nullable=True),
    )

    op.create_table(
        "microapp_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("environment", sa.String(16), nullable=False),
        sa.Column("ts", ts, server_default=sa.func.now(), nullable=False),
        sa.Column("level", sa.String(8), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("release_id", sa.String(64), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("fields", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_index("ix_microapp_logs_asset_id", "microapp_logs", ["asset_id"])

    # A binding row disappears with its environment, asset or owner (CASCADE);
    # the trigger keeps what is needed to drop the schema and roles later.
    op.execute(
        """
        CREATE FUNCTION microapp_binding_cleanup_order() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          INSERT INTO microapp_cleanup_orders
            (asset_id, database, schema_name, owner_role, runtime_role)
          SELECT e.asset_id, OLD.database, OLD.schema_name, OLD.owner_role, OLD.runtime_role
          FROM microapp_environments e WHERE e.id = OLD.environment_id;
          IF NOT FOUND THEN
            -- The environment row is already gone in this cascade; the asset
            -- id is still encoded in the schema name.
            INSERT INTO microapp_cleanup_orders
              (asset_id, database, schema_name, owner_role, runtime_role)
            VALUES (
              CAST(substr(OLD.schema_name, 3, 32) AS uuid),
              OLD.database, OLD.schema_name, OLD.owner_role, OLD.runtime_role
            );
          END IF;
          RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_microapp_binding_cleanup BEFORE DELETE ON microapp_schema_bindings "
        "FOR EACH ROW EXECUTE FUNCTION microapp_binding_cleanup_order()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_microapp_binding_cleanup ON microapp_schema_bindings")
    op.execute("DROP FUNCTION IF EXISTS microapp_binding_cleanup_order()")
    op.drop_table("microapp_logs")
    op.drop_table("microapp_cleanup_orders")
    op.drop_table("microapp_stats")
    op.drop_table("microapp_grants")
    op.drop_table("microapp_operations")
    op.drop_table("microapp_plans")
    op.drop_table("microapp_schema_bindings")
    op.drop_constraint(
        "microapp_environments_active_release_id_fkey", "microapp_environments", type_="foreignkey"
    )
    op.drop_table("microapp_releases")
    op.drop_table("microapp_environments")
