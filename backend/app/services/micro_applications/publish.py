"""Worker side of a publication operation.

Steps, each recorded on the operation so a retry after a crash resumes
instead of repeating work:

  package    the plan's bytes become a new AssetVersion through the shared
             `commit_new_version`; the operation, the version and a candidate
             release are linked in that same commit
  provision  schema, owner and runtime roles, encrypted runtime secret
  migrate    one schema version in `ics_apps` (checksum-guarded), then the
             new model and version recorded in ICS
  verify     ownership/ACL checks and a handler syntax check in a runner
  activate   compare-and-switch of `active_release_id` under the
             environment lock; only now the release is announced

There is no transaction spanning both databases and the storage: a failure
before `activate` leaves the previous release serving, and a schema change
already applied is recognised on retry instead of being run twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, secret_box
from app.config import Settings
from app.domain_errors import LimitExceededError
from app.models import (
    Asset,
    AssetVersion,
    MicroAppEnvironment,
    MicroAppOperation,
    MicroAppPlan,
    MicroAppRelease,
    MicroAppSchemaBinding,
    User,
)
from app.redis_client import get_redis
from app.services import asset_versions
from app.services.micro_applications import asset_effects, content, ddl, manifest, provisioning
from app.services.micro_applications.common import ENVIRONMENT, add_log, broker_admin
from app.services.notifications import events as notification_events
from app.services.upload import one_chunk
from app.storage import read_all, storage_from_url

log = structlog.get_logger(__name__)

SECRET_PURPOSE = "microapp-runtime-db-password"
LEASE = timedelta(seconds=45)
MAX_ATTEMPTS = 5
STEPS = ("package", "provision", "migrate", "verify", "activate")


class StepFailed(Exception):
    """A non-retryable failure: the operation ends as failed."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


class FaultInjected(Exception):
    """Test hook (local profile only)."""


async def _fault(settings: Settings, plan_id: str | None, point: str) -> None:
    """`microapp:fault:<plan_id>` = `fail:<step>` or `crash_after:<step>`."""
    if not settings.microapps_fault_injection or not plan_id:
        return
    key = f"microapp:fault:{plan_id}"
    value = await get_redis().get(key)
    if isinstance(value, bytes):
        value = value.decode()
    if value != point:
        return
    # One shot: the retried operation must get past the injected fault.
    await get_redis().delete(key)
    if point.startswith("fail:"):
        raise StepFailed("fault_injected", f"injected failure at {point}")
    raise FaultInjected(point)


async def claim(session: AsyncSession, op_id: str) -> MicroAppOperation | None:
    """Take the lease; None when another worker holds it or it is finished."""
    now = datetime.now(UTC)
    row = await session.execute(
        update(MicroAppOperation)
        .where(
            MicroAppOperation.id == op_id,
            MicroAppOperation.status.in_(("pending", "running")),
            (MicroAppOperation.lease_until.is_(None)) | (MicroAppOperation.lease_until < now),
        )
        .values(
            status="running",
            lease_until=now + LEASE,
            attempts=MicroAppOperation.attempts + 1,
        )
        .returning(MicroAppOperation.id)
    )
    claimed = row.scalar_one_or_none()
    await session.commit()
    if claimed is None:
        return None
    return await session.get(MicroAppOperation, op_id, populate_existing=True)


def _mark(op: MicroAppOperation, step: str, **info: Any) -> None:
    op.step = step
    op.steps = [*op.steps, {"step": step, "at": datetime.now(UTC).isoformat(), **info}]
    op.lease_until = datetime.now(UTC) + LEASE


async def process(session: AsyncSession, settings: Settings, op_id: str) -> str:
    op = await claim(session, op_id)
    if op is None:
        return "skipped"
    plan = await session.get(MicroAppPlan, op.plan_id) if op.plan_id else None
    try:
        if plan is None:
            raise StepFailed("plan_missing", "the plan of this operation is gone")
        done = {s["step"] for s in op.steps}
        if "package_committed" not in done:
            await _fault(settings, plan.id, "fail:package")
            await _package(session, settings, op, plan)
            await _fault(settings, plan.id, "crash_after:package")
        if "provisioned" not in done:
            await _fault(settings, plan.id, "fail:provision")
            await _provision(session, settings, op)
        if "migrated" not in done:
            await _fault(settings, plan.id, "fail:migrate")
            await _migrate(session, settings, op, plan)
            await _fault(settings, plan.id, "crash_after:migrate")
        if "verified" not in done:
            await _fault(settings, plan.id, "fail:verify")
            await _verify(session, settings, op, plan)
        await _fault(settings, plan.id, "fail:activate")
        await _activate(session, settings, op, plan)
        return "succeeded"
    except FaultInjected as e:
        # Simulated worker death: keep the lease as a crash would.
        log.warning("microapp_fault_crash", operation_id=op_id, point=str(e))
        await session.rollback()
        return "crashed"
    except StepFailed as e:
        await session.rollback()
        await _fail(session, op_id, e.code, e.detail)
        return "failed"
    except LimitExceededError as e:
        # Over quota or a limit: retrying cannot help.
        await session.rollback()
        await _fail(session, op_id, e.code, str(e))
        return "failed"
    except asyncpg.InsufficientPrivilegeError as e:
        # A privilege problem does not heal by retrying.
        await session.rollback()
        log.exception("microapp_operation_privilege_error", operation_id=op_id)
        await _fail(session, op_id, "provisioning_privilege_error", str(e)[:500])
        return "failed"
    except Exception as e:
        await session.rollback()
        log.exception("microapp_operation_error", operation_id=op_id)
        fresh = await session.get(MicroAppOperation, op_id, populate_existing=True)
        if fresh is not None and fresh.attempts >= MAX_ATTEMPTS:
            await _fail(session, op_id, "publish_error", f"{type(e).__name__}: {str(e)[:300]}")
            return "failed"
        if fresh is not None:
            # Retry from the recorded step after the lease.
            fresh.lease_until = datetime.now(UTC) + timedelta(seconds=5)
            fresh.error_detail = f"retrying after {type(e).__name__}"
            await session.commit()
        return "retry"


async def _fail(session: AsyncSession, op_id: str, code: str, detail: str) -> None:
    op = await session.get(MicroAppOperation, op_id, populate_existing=True)
    if op is None:
        return
    op.status = "failed"
    op.error_code = code
    op.error_detail = detail[:1000]
    op.finished_at = datetime.now(UTC)
    op.lease_until = None
    _mark(op, "failed", code=code)
    if op.release_id:
        rel = await session.get(MicroAppRelease, op.release_id)
        if rel is not None and rel.status == "candidate":
            rel.status = "failed"
    if op.asset_id:
        if op.action == "publish:create":
            await asset_effects.withdraw_unborn(session, op.asset_id)
        add_log(
            session,
            op.asset_id,
            "error",
            "publish",
            f"publication failed: {code}",
            fields={"operation_id": op.id, "detail": detail[:300]},
        )
        actor = await session.get(User, op.actor_id) if op.actor_id else None
        await audit.record(
            session,
            actor=actor or "system",
            action="microapp_publish_failed",
            target=f"asset:{op.asset_id}",
            payload={"operation_id": op.id, "code": code},
        )
    await session.commit()


async def _package(
    session: AsyncSession, settings: Settings, op: MicroAppOperation, plan: MicroAppPlan
) -> None:
    asset = await session.get(Asset, op.asset_id)
    actor = await session.get(User, op.actor_id) if op.actor_id else None
    if asset is None or actor is None:
        raise StepFailed("asset_missing", "asset or author no longer exists")
    storage = storage_from_url(settings.storage_url)
    files: dict[str, bytes] = {}
    for entry in plan.files:
        data = await read_all(storage, f"{plan.storage_prefix}/{entry['path']}")
        import hashlib

        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise StepFailed("package_changed", "staged package bytes do not match the plan digest")
        files[entry["path"]] = data
    total = sum(len(b) for b in files.values())

    async def stage(draft: asset_versions.VersionDraft) -> asset_versions.StagedTree:
        for path, data in files.items():
            await draft.storage.put(f"{draft.prefix}/{path}", one_chunk(data))
        return asset_versions.StagedTree(
            size_bytes=total, entry_path=plan.manifest["frontend"]["entry"], file_count=len(files)
        )

    m = plan.manifest

    async def link(version_row: AssetVersion) -> None:
        release = MicroAppRelease(
            asset_id=asset.id,
            asset_version_id=version_row.id,
            package_version=version_row.version,
            digest=plan.digest,
            manifest=m,
            contract_version=m["apiVersion"],
            profile=m["runtime"]["profile"],
            schema_min=m["compatibility"]["schemaMin"],
            schema_max=m["compatibility"]["schemaMax"],
            target_schema_version=plan.migration["schema_version_to"],
            validation={
                "warnings": plan.diagnostics.get("warnings", []),
                "validator": manifest.VALIDATOR_VERSION,
            },
            status="candidate",
            created_by=actor.id,
        )
        session.add(release)
        await session.flush()
        live = await session.get(MicroAppOperation, op.id)
        assert live is not None
        live.asset_version_id = version_row.id
        live.release_id = release.id
        _mark(live, "package_committed", package_version=version_row.version)

    await asset_versions.commit_new_version(
        session,
        asset,
        settings,
        stage=stage,
        actor=actor,
        audit_action="asset_versioned",
        audit_payload=lambda nv: {"version": nv.version, "kind": asset.kind, "operation_id": op.id},
        change_note=plan.change_note,
        before_commit=link,
    )
    await session.refresh(op)


async def _binding(session: AsyncSession, env: MicroAppEnvironment) -> MicroAppSchemaBinding | None:
    return await session.scalar(
        select(MicroAppSchemaBinding).where(MicroAppSchemaBinding.environment_id == env.id)
    )


async def _env(session: AsyncSession, asset_id: Any, *, lock: bool = False) -> MicroAppEnvironment:
    stmt = select(MicroAppEnvironment).where(
        MicroAppEnvironment.asset_id == asset_id, MicroAppEnvironment.environment == ENVIRONMENT
    )
    if lock:
        stmt = stmt.with_for_update()
    env = await session.scalar(stmt)
    if env is None:
        raise StepFailed("environment_missing", "environment row is gone")
    return env


async def _provision(session: AsyncSession, settings: Settings, op: MicroAppOperation) -> None:
    env = await _env(session, op.asset_id)
    names = provisioning.Names.for_asset(
        env.asset_hex, ENVIRONMENT, provisioning.apps_database(settings)
    )
    binding = await _binding(session, env)
    if binding is None:
        password = provisioning.new_password()
        binding = MicroAppSchemaBinding(
            environment_id=env.id,
            database=names.database,
            schema_name=names.schema,
            owner_role=names.owner,
            runtime_role=names.runtime,
            secret_ciphertext=secret_box.encrypt(settings, SECRET_PURPOSE, password),
        )
        session.add(binding)
        # Committed before the roles exist, so a crash leaves a cleanup trail.
        await session.commit()
    secret = secret_box.decrypt(settings, SECRET_PURPOSE, binding.secret_ciphertext)
    if secret is None:
        raise StepFailed("secret_unreadable", "the runtime secret cannot be decrypted")
    async with provisioning.provisioner(settings) as conn:
        await provisioning.ensure_roles_and_schema(conn, names, secret)
        reader = settings.microapps_reader_role
        if reader and not await provisioning.grant_reader(conn, names, reader):
            log.warning("microapp_reader_role_missing", role=reader)
    binding.provisioned_at = binding.provisioned_at or datetime.now(UTC)
    live = await session.get(MicroAppOperation, op.id)
    assert live is not None
    _mark(live, "provisioned", schema=names.schema)
    await session.commit()


async def _migrate(
    session: AsyncSession, settings: Settings, op: MicroAppOperation, plan: MicroAppPlan
) -> None:
    env = await _env(session, op.asset_id, lock=True)
    names = provisioning.Names.for_asset(
        env.asset_hex, ENVIRONMENT, provisioning.apps_database(settings)
    )
    new_model = manifest.data_model(plan.manifest)
    delta = ddl.diff(names.schema, env.applied_model or {}, new_model)
    if delta.destructive:
        raise StepFailed("destructive_change", delta.destructive[0]["reason"])
    collections = list(new_model)
    # Seed rows of the collections this migration creates, in its transaction,
    # read from the committed package (the plan keeps only their counts).
    seeded = [
        c for c in (plan.migration or {}).get("seed_rows", {}) if c in delta.collections_added
    ]
    seeds: dict[str, list[dict[str, Any]]] = {}
    if seeded:
        version = await session.get(AssetVersion, op.asset_version_id)
        if version is None:
            raise StepFailed("package_missing", "the committed package version is gone")
        seeds = await content.read_seed_rows(settings, version.storage_prefix, seeded)
    seed_statements = content.seed_statements(
        names.schema, new_model, seeds, created_by=plan.user_id, plan_id=plan.id
    )
    async with provisioning.provisioner(settings) as conn:
        if delta.changes_schema:
            target = env.schema_version + 1
            outcome = await provisioning.migrate(
                conn,
                names,
                version=target,
                statements=delta.statements,
                seed_statements=seed_statements,
                collections=collections,
                operation_id=op.id,
            )
            env.schema_version = target
            env.applied_model = new_model
        else:
            await provisioning.grant_collections(conn, names, collections)
            outcome = "no_change"
    live = await session.get(MicroAppOperation, op.id)
    assert live is not None
    _mark(live, "migrated", outcome=outcome, schema_version=env.schema_version)
    add_log(
        session,
        env.asset_id,
        "info",
        "publish",
        f"database {outcome}",
        fields={"schema_version": env.schema_version, "operation_id": op.id},
    )
    await session.commit()


async def _verify(
    session: AsyncSession, settings: Settings, op: MicroAppOperation, plan: MicroAppPlan
) -> None:
    env = await _env(session, op.asset_id)
    names = provisioning.Names.for_asset(
        env.asset_hex, ENVIRONMENT, provisioning.apps_database(settings)
    )
    release = await session.get(MicroAppRelease, op.release_id)
    if release is None:
        raise StepFailed("release_missing", "candidate release is gone")
    if not release.schema_min <= env.schema_version <= release.schema_max:
        raise StepFailed("schema_incompatible", "the release does not support the database schema")
    async with provisioning.provisioner(settings) as conn:
        problems = await provisioning.verify(
            conn, names, list(manifest.data_model(plan.manifest)), settings.microapps_reader_role
        )
    if problems:
        raise StepFailed("acl_check_failed", "; ".join(problems)[:900])
    storage = storage_from_url(settings.storage_url)
    version = await session.get(AssetVersion, op.asset_version_id)
    assert version is not None
    handlers = {}
    for entry in plan.files:
        if entry["path"].startswith("handlers/"):
            data = await read_all(storage, f"{version.storage_prefix}/{entry['path']}")
            handlers[entry["path"]] = data.decode("utf-8")
    if handlers:
        result = await broker_admin(settings, "POST", "/admin/compile", {"files": handlers})
        bad = {p: r for p, r in result.get("results", {}).items() if not r.get("ok")}
        if bad:
            raise StepFailed("handler_compile_failed", f"handlers failed to compile: {sorted(bad)}")
    live = await session.get(MicroAppOperation, op.id)
    assert live is not None
    _mark(live, "verified")
    await session.commit()


async def _activate(
    session: AsyncSession, settings: Settings, op: MicroAppOperation, plan: MicroAppPlan
) -> None:
    env = await _env(session, op.asset_id, lock=True)
    previous = op.result.get("previous_release_id")
    current = str(env.active_release_id) if env.active_release_id else None
    if current != previous:
        raise StepFailed(
            "generation_conflict",
            "another release was activated meanwhile; plan again from the current state",
        )
    release = await session.get(MicroAppRelease, op.release_id)
    assert release is not None
    old = (
        await session.get(MicroAppRelease, env.active_release_id) if env.active_release_id else None
    )
    if old is not None:
        old.status = "superseded"
    release.status = "active"
    release.activated_at = datetime.now(UTC)
    env.active_release_id = release.id
    # The broker drops its cached context; a suspended app stays suspended.
    env.control_generation += 1
    asset = await session.get(Asset, op.asset_id)
    assert asset is not None
    asset_effects.follow_manifest(asset, old.manifest if old else None, plan.manifest)
    live = await session.get(MicroAppOperation, op.id)
    assert live is not None
    live.status = "succeeded"
    live.finished_at = datetime.now(UTC)
    live.lease_until = None
    live.error_code = None
    live.error_detail = None
    live.result = {
        **live.result,
        "release_id": str(release.id),
        "package_version": release.package_version,
        "schema_version": env.schema_version,
    }
    _mark(live, "activated", release_id=str(release.id))
    add_log(
        session,
        asset.id,
        "info",
        "publish",
        "release activated",
        release_id=str(release.id),
        fields={"operation_id": op.id, "digest": release.digest},
    )
    actor = await session.get(User, op.actor_id) if op.actor_id else None
    await audit.record(
        session,
        actor=actor or "system",
        action="microapp_published",
        target=f"asset:{asset.id}",
        payload={"operation_id": op.id, "release_id": str(release.id), "digest": release.digest},
    )
    await session.commit()
    if old is None:
        # The first release is the app's birth for its watchers, as a new
        # document is; a failed first publication never announced one.
        await notification_events.emit_created(asset, actor)
    else:
        await notification_events.emit_updated(asset, release.package_version, actor, settings)
