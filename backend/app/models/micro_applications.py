"""Micro-applications: platform records next to the `micro_application` asset.

The asset row and its `AssetVersion`s hold the immutable package history.
Everything that decides what runs (active release, desired state, database
binding, publication operations) lives here, never in `Asset.properties`,
which owners can edit through the metadata API.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TS = TIMESTAMP(timezone=True)


class MicroAppEnvironment(Base):
    """One running environment of a micro-application (`prod` in the PoC)."""

    __tablename__ = "microapp_environments"
    __table_args__ = (
        UniqueConstraint("asset_id", "environment", name="uq_microapp_env_asset_env"),
        CheckConstraint("desired_state IN ('enabled','suspended')", name="ck_microapp_env_desired"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    environment: Mapped[str] = mapped_column(String(16))
    # Lower-case hex of the asset id: the label of the app origin and the
    # schema/role names. Derived once, never from manifest input.
    asset_hex: Mapped[str] = mapped_column(String(32), unique=True)
    # Label of the public app origin; identifies the app, never authorizes.
    host_name: Mapped[str] = mapped_column(
        String(8), ForeignKey("microapp_host_names.name"), unique=True
    )
    desired_state: Mapped[str] = mapped_column(
        String(16), default="enabled", server_default="enabled"
    )
    active_release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("microapp_releases.id", ondelete="SET NULL", use_alter=True)
    )
    schema_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Data model (collections and fields, no access rules) the database was
    # last migrated to; plans diff the next manifest against it.
    applied_model: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    data_generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    policy_generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Bumped by every control action and every publish; the broker drops its
    # cached context when it sees a newer value.
    control_generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    suspended_at: Mapped[datetime | None] = mapped_column(TS)
    suspended_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())


class MicroAppSchemaBinding(Base):
    """Database binding of one environment. Names are set by the platform."""

    __tablename__ = "microapp_schema_bindings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("microapp_environments.id", ondelete="CASCADE"), unique=True
    )
    database: Mapped[str] = mapped_column(String(63))
    schema_name: Mapped[str] = mapped_column(String(63))
    owner_role: Mapped[str] = mapped_column(String(63))
    runtime_role: Mapped[str] = mapped_column(String(63))
    # Runtime password, encrypted with a dedicated secret_box purpose; only
    # the broker gets the plain value, over the internal API.
    secret_ciphertext: Mapped[str] = mapped_column(Text)
    credential_generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    provisioned_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class MicroAppRelease(Base):
    """An immutable, validated package version that may be activated."""

    __tablename__ = "microapp_releases"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate','active','superseded','failed')",
            name="ck_microapp_release_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    asset_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="CASCADE"), unique=True
    )
    package_version: Mapped[int] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(String(80))
    manifest: Mapped[dict] = mapped_column(JSONB)
    contract_version: Mapped[str] = mapped_column(String(64))
    profile: Mapped[str] = mapped_column(String(64))
    schema_min: Mapped[int] = mapped_column(Integer)
    schema_max: Mapped[int] = mapped_column(Integer)
    target_schema_version: Mapped[int] = mapped_column(Integer)
    validation: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(String(16), default="candidate", server_default="candidate")
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    activated_at: Mapped[datetime | None] = mapped_column(TS)


class MicroAppPlan(Base):
    """A checked package bound to its digest; apply accepts only this."""

    __tablename__ = "microapp_plans"
    __table_args__ = (
        CheckConstraint("action IN ('create','update')", name="ck_microapp_plan_action"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(8))
    asset_id: Mapped[UUID | None] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    digest: Mapped[str] = mapped_column(String(80))
    # Staged bytes of the package (storage key prefix), written at plan time.
    storage_prefix: Mapped[str] = mapped_column(Text)
    files: Mapped[list] = mapped_column(JSONB)
    manifest: Mapped[dict] = mapped_column(JSONB)
    contract_version: Mapped[str] = mapped_column(String(64))
    expected_generation: Mapped[int] = mapped_column(Integer)
    migration: Mapped[dict] = mapped_column(JSONB)
    diagnostics: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    #: The author's words for the release; the package version's change note.
    change_note: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(TS, index=True)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class MicroAppOperation(Base):
    """Durable publication or control operation; survives worker restarts."""

    __tablename__ = "microapp_operations"
    __table_args__ = (
        UniqueConstraint("actor_id", "idempotency_key", name="uq_microapp_op_idempotency"),
        CheckConstraint(
            "status IN ('pending','running','succeeded','failed')",
            name="ck_microapp_op_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    action: Mapped[str] = mapped_column(String(32))
    asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    plan_id: Mapped[str | None] = mapped_column(
        ForeignKey("microapp_plans.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    step: Mapped[str] = mapped_column(String(32), default="accepted", server_default="accepted")
    steps: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    asset_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("asset_versions.id", ondelete="SET NULL")
    )
    release_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("microapp_releases.id", ondelete="SET NULL")
    )
    result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=func.now(), onupdate=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class MicroAppGrant(Base):
    """A business permission of the app given to a person or to the accepted
    members of a project. Revoking the membership revokes what it gave."""

    __tablename__ = "microapp_grants"
    __table_args__ = (
        CheckConstraint("num_nonnulls(user_id, project_id) = 1", name="ck_microapp_grant_one"),
        UniqueConstraint(
            "asset_id",
            "environment",
            "permission",
            "user_id",
            "project_id",
            name="uq_microapp_grant",
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    environment: Mapped[str] = mapped_column(String(16))
    permission: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    project_id: Mapped[UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())


class MicroAppStats(Base):
    """Latest measurements: runtime state from the broker, data size from the
    collector. Display only, never an authorization source."""

    __tablename__ = "microapp_stats"

    environment_id: Mapped[UUID] = mapped_column(
        ForeignKey("microapp_environments.id", ondelete="CASCADE"), primary_key=True
    )
    runtime_state: Mapped[str | None] = mapped_column(String(16))
    runtime_sampled_at: Mapped[datetime | None] = mapped_column(TS)
    broker_incarnation: Mapped[str | None] = mapped_column(String(64))
    inflight: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    queued: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    open_connections: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_used_at: Mapped[datetime | None] = mapped_column(TS)
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_at: Mapped[datetime | None] = mapped_column(TS)
    breaker_open_until: Mapped[datetime | None] = mapped_column(TS)
    db_bytes: Mapped[int | None] = mapped_column(BigInteger)
    db_rows_estimate: Mapped[int | None] = mapped_column(BigInteger)
    db_tables: Mapped[int | None] = mapped_column(Integer)
    db_sampled_at: Mapped[datetime | None] = mapped_column(TS)


class MicroAppCleanupOrder(Base):
    """What to drop after an environment row is gone. Written by a database
    trigger on binding deletion, so it survives any cascade (asset or owner
    deleted); deliberately without foreign keys."""

    __tablename__ = "microapp_cleanup_orders"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    asset_id: Mapped[UUID] = mapped_column()
    database: Mapped[str] = mapped_column(String(63))
    schema_name: Mapped[str] = mapped_column(String(63))
    owner_role: Mapped[str] = mapped_column(String(63))
    runtime_role: Mapped[str] = mapped_column(String(63))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class MicroAppLog(Base):
    """Redacted application, publication and control log lines."""

    __tablename__ = "microapp_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_id: Mapped[UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    environment: Mapped[str] = mapped_column(String(16))
    ts: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    level: Mapped[str] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(16))
    request_id: Mapped[str | None] = mapped_column(String(64))
    release_id: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    fields: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
