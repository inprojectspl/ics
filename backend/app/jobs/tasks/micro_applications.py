"""Arq tasks of micro-applications: durable publication operations, control
retries, cleanup after deletion and data measurements. The operation row is
written before any enqueue, so a lost job is found again by the sweeper."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, or_, select

from app import quota
from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    MicroAppCleanupOrder,
    MicroAppEnvironment,
    MicroAppOperation,
    MicroAppPlan,
    MicroAppStats,
)
from app.services.micro_applications import control as control_svc
from app.services.micro_applications import provisioning, publish
from app.storage import storage_from_url

log = structlog.get_logger(__name__)


async def enqueue_operation(op_id: str, *, defer_s: int = 0) -> None:
    from app.jobs.queue import enqueue

    try:
        await enqueue(
            "microapp_process_operation",
            op_id,
            _job_id=f"microapp-op:{op_id}:{int(datetime.now(UTC).timestamp())}",
            _defer_by=defer_s or None,
        )
    except Exception:
        # Redis down: the sweeper picks the pending operation up later.
        log.warning("microapp_enqueue_failed", operation_id=op_id)


async def enqueue_control_retry(op_id: str) -> None:
    from app.jobs.queue import enqueue

    try:
        await enqueue("microapp_control_retry", op_id, _defer_by=3)
    except Exception:
        log.warning("microapp_enqueue_failed", operation_id=op_id)


async def microapp_process_operation(ctx: dict, op_id: str) -> dict:
    settings = get_settings()
    if not settings.microapps_enabled:
        # Stays pending; the sweeper resumes it once the feature is back on.
        return {"operation_id": op_id, "skipped": "disabled"}
    async with SessionLocal() as session:
        outcome = await publish.process(session, settings, op_id)
    if outcome == "retry":
        await enqueue_operation(op_id, defer_s=5)
    return {"operation_id": op_id, "outcome": outcome}


async def microapp_control_retry(ctx: dict, op_id: str) -> dict:
    settings = get_settings()
    if not settings.microapps_enabled:
        return {"operation_id": op_id, "skipped": "disabled"}
    async with SessionLocal() as session:
        await control_svc.finish_runtime_action(session, settings, op_id)
    return {"operation_id": op_id}


async def microapp_sweeper(ctx: dict) -> dict:
    """Every 30 s: resume operations whose lease expired, finish control
    actions still draining, run cleanup orders, drop expired plans, refresh
    data measurements."""
    settings = get_settings()
    if not settings.microapps_enabled:
        return {"skipped": "disabled"}
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        stuck = list(
            await session.scalars(
                select(MicroAppOperation.id).where(
                    MicroAppOperation.status.in_(("pending", "running")),
                    MicroAppOperation.action.like("publish:%"),
                    or_(
                        MicroAppOperation.lease_until.is_(None), MicroAppOperation.lease_until < now
                    ),
                    MicroAppOperation.created_at < now - timedelta(seconds=10),
                )
            )
        )
        draining = list(
            await session.scalars(
                select(MicroAppOperation.id).where(
                    MicroAppOperation.status == "running",
                    MicroAppOperation.action.like("control:%"),
                    MicroAppOperation.updated_at < now - timedelta(seconds=10),
                )
            )
        )
    for op_id in stuck:
        await enqueue_operation(op_id)
    for op_id in draining:
        await enqueue_control_retry(op_id)
    cleaned = await _cleanup(settings)
    expired = await _drop_expired_plans(settings)
    measured = await _measure(settings)
    return {
        "resumed": len(stuck),
        "draining": len(draining),
        "cleaned": cleaned,
        "plans_dropped": expired,
        "measured": measured,
    }


# A plan outlives its TTL by a day, so an apply racing the expiry still
# reads its files; a running publication keeps its plan whatever its age.
PLAN_GRACE = timedelta(days=1)


async def _drop_expired_plans(settings, batch: int = 50) -> int:
    """Expired plans and their stored packages: a package that was applied
    lives on as a package version, one that was not is never used. The
    storage goes first, outside the transaction; a plan whose files are gone
    is dropped on the next run if this one stops halfway."""
    now = datetime.now(UTC)
    running = select(MicroAppOperation.id).where(
        MicroAppOperation.plan_id == MicroAppPlan.id,
        MicroAppOperation.status.in_(("pending", "running")),
    )
    async with SessionLocal() as session:
        expired = (
            await session.execute(
                select(MicroAppPlan.id, MicroAppPlan.storage_prefix)
                .where(MicroAppPlan.expires_at < now - PLAN_GRACE, ~running.exists())
                .limit(batch)
            )
        ).all()
    if not expired:
        return 0
    storage = storage_from_url(settings.storage_url)
    gate = asyncio.Semaphore(8)

    async def drop_files(prefix: str) -> None:
        async with gate:
            await storage.delete_prefix(f"{prefix}/")

    await asyncio.gather(*(drop_files(prefix) for _, prefix in expired))
    async with SessionLocal() as session:
        await session.execute(
            delete(MicroAppPlan).where(MicroAppPlan.id.in_([plan_id for plan_id, _ in expired]))
        )
        await session.commit()
    return len(expired)


async def _cleanup(settings) -> int:
    done = 0
    async with SessionLocal() as session:
        orders = list(
            await session.scalars(
                select(MicroAppCleanupOrder)
                .where(MicroAppCleanupOrder.status == "pending", MicroAppCleanupOrder.attempts < 10)
                .limit(20)
            )
        )
        if not orders or not settings.microapps_apps_database_url:
            return 0
        async with provisioning.provisioner(settings) as conn:
            for order in orders:
                names = provisioning.Names(
                    order.database, order.schema_name, order.owner_role, order.runtime_role
                )
                order.attempts += 1
                try:
                    await provisioning.drop(conn, names)
                    order.status = "done"
                    order.finished_at = datetime.now(UTC)
                    done += 1
                except Exception as e:
                    order.last_error = f"{type(e).__name__}: {str(e)[:300]}"
                await session.commit()
    return done


async def _measure(settings) -> int:
    if not settings.microapps_apps_database_url:
        return 0
    async with SessionLocal() as session:
        envs = list(await session.scalars(select(MicroAppEnvironment)))
        if not envs:
            return 0
        names = {
            e.id: provisioning.Names.for_asset(e.asset_hex, e.environment).schema for e in envs
        }
        try:
            async with provisioning.provisioner(settings) as conn:
                sizes = await provisioning.measure(conn, list(names.values()))
        except Exception:
            log.warning("microapp_measure_failed")
            return 0
        now = datetime.now(UTC)
        for env in envs:
            m = sizes.get(names[env.id])
            stats = await session.get(MicroAppStats, env.id)
            if stats is None:
                stats = MicroAppStats(environment_id=env.id)
                session.add(stats)
            if m is None:
                continue
            stats.db_bytes = m["bytes"]
            stats.db_rows_estimate = m["rows"]
            stats.db_tables = m["tables"]
            stats.db_sampled_at = now
        await session.commit()
        await quota.refresh_full_owners(session)
        return len(sizes)
