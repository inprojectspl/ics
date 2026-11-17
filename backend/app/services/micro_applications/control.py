"""Control actions shared by the ICS panel and MCP (one domain service).

- enable:  desired_state=enabled; the app stays asleep until a real request.
- suspend: desired_state=suspended is committed first (new requests get 503
           at once), then the broker drains in-flight work. The operation is
           finished only after a confirmed drain.
- sleep:   free pools, caches and runner leases now; no state change.
- restart: new control generation, drain, recycle runner processes. Never
           lifts a suspension.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.config import Settings
from app.domain_errors import AccessDeniedError, ConflictError, InvalidInputError, NotFoundError
from app.models import MicroAppOperation, User
from app.services.micro_applications import access
from app.services.micro_applications.common import (
    ENVIRONMENT,
    add_log,
    broker_admin,
    canonical_hash,
    load_app,
    new_id,
)
from app.services.micro_applications.operations import operation_view

log = structlog.get_logger(__name__)
ACTIONS = ("enable", "suspend", "sleep", "restart")


async def control(
    session: AsyncSession,
    settings: Settings,
    user: User,
    asset_id: Any,
    *,
    action: str,
    expected_generation: int,
    idempotency_key: str,
) -> tuple[dict[str, Any], bool]:
    if action not in ACTIONS:
        raise InvalidInputError(
            "invalid_action", "unknown action", field="action", extra={"allowed": list(ACTIONS)}
        )
    request_hash = canonical_hash(
        {"asset": str(asset_id), "action": action, "expected_generation": expected_generation}
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
        _, env = await load_app(session, existing.asset_id)
        return operation_view(existing, settings, env), False

    asset, env = await load_app(session, asset_id, lock=True)
    r = await access.rights(session, user, asset)
    if not r.use:
        raise NotFoundError("not_found", "micro-application not found")
    if not r.control:
        raise AccessDeniedError("control_permission_required", "app.control is required")
    if env.control_generation != expected_generation:
        raise ConflictError(
            "generation_conflict",
            "the application changed; read its status and retry with the current generation",
            field="expected_generation",
            extra={"current_generation": env.control_generation},
        )
    now = datetime.now(UTC)
    if action == "enable":
        env.desired_state = "enabled"
        env.suspended_at = None
        env.suspended_by = None
        env.control_generation += 1
    elif action == "suspend":
        env.desired_state = "suspended"
        env.suspended_at = now
        env.suspended_by = user.id
        env.control_generation += 1
    elif action == "restart":
        env.control_generation += 1
    op = MicroAppOperation(
        id=new_id("op"),
        action=f"control:{action}",
        asset_id=asset.id,
        actor_id=user.id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status="running" if action in ("suspend", "sleep", "restart") else "succeeded",
        step="state_committed",
        steps=[{"step": "state_committed", "at": now.isoformat()}],
        result={"desired_state": env.desired_state, "control_generation": env.control_generation},
        finished_at=None if action in ("suspend", "sleep", "restart") else now,
    )
    session.add(op)
    add_log(
        session,
        asset.id,
        "info",
        "control",
        f"{action} requested",
        fields={"operation_id": op.id, "by": str(user.id)},
    )
    await audit.record(
        session,
        actor=user,
        action="microapp_controlled",
        target=f"asset:{asset.id}",
        payload={"action": action, "operation_id": op.id, "generation": env.control_generation},
    )
    await session.commit()
    if op.status == "running":
        await finish_runtime_action(session, settings, op.id)
        await session.refresh(op)
    return operation_view(op, settings, env), True


async def finish_runtime_action(session: AsyncSession, settings: Settings, op_id: str) -> None:
    """Ask the broker to drain/sleep/restart. Unreachable broker: the
    operation stays `running` (draining) and a retry job comes back to it;
    the committed desired state already blocks new requests."""
    op = await session.get(MicroAppOperation, op_id, populate_existing=True)
    if op is None or op.status != "running" or not op.action.startswith("control:"):
        return
    action = op.action.split(":", 1)[1]
    _, env = await load_app(session, op.asset_id)
    try:
        result = await broker_admin(
            settings, "POST", f"/admin/apps/{env.asset_hex}/{ENVIRONMENT}/{action}"
        )
    except Exception as e:
        op.step = "draining"
        op.error_detail = f"broker unreachable: {type(e).__name__}"
        await session.commit()
        from app.jobs.tasks.micro_applications import enqueue_control_retry

        await enqueue_control_retry(op.id)
        return
    now = datetime.now(UTC)
    if result.get("drained"):
        op.status = "succeeded"
        op.finished_at = now
        op.error_detail = None
        op.steps = [*op.steps, {"step": "drained", "at": now.isoformat()}]
        op.step = "drained"
    else:
        op.step = "draining"
        op.steps = [
            *op.steps,
            {"step": "draining", "at": now.isoformat(), "inflight": result.get("inflight")},
        ]
        from app.jobs.tasks.micro_applications import enqueue_control_retry

        await session.commit()
        await enqueue_control_retry(op.id)
        return
    await session.commit()
