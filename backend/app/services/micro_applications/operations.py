"""Apply and operation reads: the durable side of a plan.

Apply re-checks the caller, the plan, its digest and generation, then
reserves one operation (and for a new app its asset and environment) in one
commit and hands it to the worker. The same key with the same request
returns that operation again.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.config import Settings
from app.constants import MICRO_APPLICATION
from app.domain_errors import AccessDeniedError, ConflictError, NotFoundError
from app.models import Asset, MicroAppEnvironment, MicroAppOperation, MicroAppPlan, User
from app.services.micro_applications import access
from app.services.micro_applications.common import (
    ENVIRONMENT,
    add_log,
    canonical_hash,
    load_app,
    new_id,
)
from app.services.micro_applications.hosts import allocate_host_name, app_url
from app.slug import generate_slug


def operation_view(
    op: MicroAppOperation, settings: Settings, env: MicroAppEnvironment | None
) -> dict[str, Any]:
    terminal = op.status in ("succeeded", "failed")
    return {
        "operation_id": op.id,
        "action": op.action,
        "status": op.status,
        "terminal": terminal,
        "step": op.step,
        "steps": op.steps,
        "asset_id": str(op.asset_id) if op.asset_id else None,
        "release_id": str(op.release_id) if op.release_id else None,
        "app_url": app_url(settings, env) if env else None,
        "error": {"code": op.error_code, "detail": op.error_detail} if op.error_code else None,
        "result": op.result,
        "attempts": op.attempts,
        "created_at": op.created_at.isoformat() if op.created_at else None,
        "finished_at": op.finished_at.isoformat() if op.finished_at else None,
    }


async def apply_plan(
    session: AsyncSession,
    settings: Settings,
    user: User,
    plan_id: str,
    *,
    digest: str,
    expected_generation: int,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    """Returns (operation view, created). A repeated call with the same key
    and request returns the same operation and enqueues nothing new."""
    request_hash = canonical_hash(
        {"plan": plan_id, "digest": digest, "expected_generation": expected_generation}
    )
    existing = await session.scalar(
        select(MicroAppOperation).where(
            MicroAppOperation.actor_id == user.id,
            MicroAppOperation.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise ConflictError(
                "idempotency_key_reused", "this idempotency_key was used for a different request"
            )
        return operation_view(existing, settings, await _env(session, existing.asset_id)), False

    plan = await session.get(MicroAppPlan, plan_id, with_for_update=True)
    if plan is None or plan.user_id != user.id:
        raise NotFoundError("plan_not_found", "plan not found", field="plan_id")
    if plan.expires_at < datetime.now(UTC):
        raise ConflictError("plan_expired", "the plan expired; create a new plan")
    if plan.digest != digest:
        raise ConflictError("digest_mismatch", "the digest does not match the plan", field="digest")
    if plan.expected_generation != expected_generation:
        raise ConflictError(
            "generation_conflict",
            "expected_generation does not match the plan",
            field="expected_generation",
        )
    consumed = await session.scalar(
        select(MicroAppOperation.id).where(MicroAppOperation.plan_id == plan.id)
    )
    if consumed is not None:
        raise ConflictError("plan_already_applied", "this plan was applied by another request")

    op_id = new_id("op")
    if plan.action == "create":
        asset = Asset(
            id=uuid4(),
            slug=generate_slug(),
            owner_id=user.id,
            project_id=plan.project_id,
            kind=MICRO_APPLICATION,
            title=plan.manifest["metadata"]["title"],
            summary=plan.manifest["metadata"].get("description"),
            summary_source="agent",
            storage_prefix="",
            entry_path=plan.manifest["frontend"]["entry"],
            version=0,
            size_bytes=0,
            security_status="clean",
        )
        asset.storage_prefix = f"assets/{asset.id}"
        session.add(asset)
        await session.flush()
        env = MicroAppEnvironment(
            asset_id=asset.id,
            environment=ENVIRONMENT,
            asset_hex=asset.id.hex,
            host_name=await allocate_host_name(session, settings, asset.id),
            desired_state="enabled",
        )
        session.add(env)
        previous_release = None
    else:
        asset, env = await load_app(session, plan.asset_id, lock=True)
        r = await access.rights(session, user, asset)
        if not r.publish:
            raise AccessDeniedError(
                "publish_permission_required",
                "app.publish is required to apply a release; the plan is ready for a publisher",
            )
        if env.control_generation != expected_generation:
            raise ConflictError(
                "generation_conflict",
                "the application changed since the plan; create a new plan",
                field="expected_generation",
            )
        previous_release = str(env.active_release_id) if env.active_release_id else None
    op = MicroAppOperation(
        id=op_id,
        action=f"publish:{plan.action}",
        asset_id=asset.id,
        actor_id=user.id,
        plan_id=plan.id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status="pending",
        step="accepted",
        steps=[{"step": "accepted", "at": datetime.now(UTC).isoformat()}],
        result={"previous_release_id": previous_release, "digest": plan.digest},
    )
    session.add(op)
    add_log(
        session,
        asset.id,
        "info",
        "publish",
        "publication accepted",
        fields={"operation_id": op_id, "digest": plan.digest},
    )
    await audit.record(
        session,
        actor=user,
        action="microapp_apply_accepted",
        target=f"asset:{asset.id}",
        payload={"operation_id": op_id, "plan_id": plan.id, "digest": plan.digest},
    )
    await session.commit()
    # After the commit: a lost enqueue is picked up by the operation sweeper.
    from app.jobs.tasks.micro_applications import enqueue_operation

    await enqueue_operation(op_id)
    return operation_view(op, settings, env), True


async def _env(session: AsyncSession, asset_id: Any) -> MicroAppEnvironment | None:
    if asset_id is None:
        return None
    return await session.scalar(
        select(MicroAppEnvironment).where(MicroAppEnvironment.asset_id == asset_id)
    )


async def get_operation(
    session: AsyncSession, settings: Settings, user: User, op_id: str
) -> dict[str, Any]:
    op = await session.get(MicroAppOperation, op_id)
    if op is None:
        raise NotFoundError("operation_not_found", "operation not found")
    if op.actor_id != user.id:
        asset = await session.get(Asset, op.asset_id) if op.asset_id else None
        if asset is None or not (await access.rights(session, user, asset)).control:
            raise NotFoundError("operation_not_found", "operation not found")
    return operation_view(op, settings, await _env(session, op.asset_id))
