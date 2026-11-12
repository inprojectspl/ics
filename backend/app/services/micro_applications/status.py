"""Read side for the panel and MCP: list, detail, logs, releases and
the author-only package read. Reading status never wakes an application:
it touches only ICS tables (stats are written by the broker and collector).
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.config import Settings
from app.constants import MICRO_APPLICATION
from app.domain_errors import AccessDeniedError, NotFoundError
from app.models import (
    Asset,
    AssetVersion,
    MicroAppEnvironment,
    MicroAppLog,
    MicroAppOperation,
    MicroAppRelease,
    MicroAppStats,
    Project,
    User,
)
from app.permissions import visible_assets_filter
from app.services.document_search import search_filter
from app.services.micro_applications import access
from app.services.micro_applications.common import app_url, load_app
from app.storage import read_all, storage_from_url

# Broker reports arrive every ~10 s; older samples are shown as unknown.
RUNTIME_SAMPLE_TTL = timedelta(seconds=45)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def broker_incarnation() -> str | None:
    """Incarnation of the broker that reported in the last minute, if any."""
    import json

    from app.redis_client import get_redis
    from app.services.micro_applications.runtime import BROKER_HEARTBEAT_KEY

    raw = await get_redis().get(BROKER_HEARTBEAT_KEY)
    if not raw:
        return None
    value: str | None = json.loads(raw).get("incarnation")
    return value


def _runtime(
    env: MicroAppEnvironment, stats: MicroAppStats | None, broker: str | None = None
) -> dict[str, Any]:
    now = datetime.now(UTC)
    # Last use and last error stay true whatever happened to the context since.
    history = stats
    if stats and broker and stats.broker_incarnation and stats.broker_incarnation != broker:
        # The live broker has not served this app since it started: no pool,
        # cache or runner lease exists for it.
        stats = None
    fresh = bool(
        stats and stats.runtime_sampled_at and now - stats.runtime_sampled_at < RUNTIME_SAMPLE_TTL
    )
    if (
        fresh
        and stats
        and stats.runtime_sampled_at
        and env.updated_at
        and stats.runtime_sampled_at < env.updated_at
    ):
        # Sampled before the last control action or publication: the broker
        # drops that context on the next request, so the sample says nothing
        # about the current one.
        fresh = False
        stats = None
    if env.desired_state == "suspended":
        state = "suspended" if not (fresh and stats and stats.inflight) else "draining"
    elif stats is None or stats.runtime_state is None:
        # Never used since the broker started: nothing runs for it.
        state = "sleeping"
    elif not fresh:
        state = "unknown"
    else:
        state = stats.runtime_state
    return {
        "state": state,
        "sampled_at": _iso(stats.runtime_sampled_at) if stats else None,
        "fresh": fresh,
        "inflight": stats.inflight if stats and fresh else 0,
        "queued": stats.queued if stats and fresh else 0,
        "open_connections": stats.open_connections if stats and fresh else 0,
        "last_used_at": _iso(history.last_used_at) if history else None,
        "last_error": (
            {"code": history.last_error_code, "at": _iso(history.last_error_at)}
            if history and history.last_error_code
            else None
        ),
        "breaker_open_until": _iso(stats.breaker_open_until) if stats else None,
    }


def _data(stats: MicroAppStats | None, env: MicroAppEnvironment) -> dict[str, Any]:
    measured = bool(stats and stats.db_sampled_at)
    return {
        "measured": measured,
        "sampled_at": _iso(stats.db_sampled_at) if stats else None,
        "bytes": stats.db_bytes if measured and stats else None,
        "rows_estimate": stats.db_rows_estimate if measured and stats else None,
        "tables": stats.db_tables if measured and stats else None,
        "schema_version": env.schema_version,
    }


async def _view(
    session: AsyncSession,
    settings: Settings,
    user: User,
    asset: Asset,
    env: MicroAppEnvironment,
    stats: MicroAppStats | None,
    *,
    owner: User | None,
    project: Project | None,
    broker: str | None = None,
) -> dict[str, Any]:
    r = await access.rights(session, user, asset)
    release = (
        await session.get(MicroAppRelease, env.active_release_id) if env.active_release_id else None
    )
    last_op = await session.scalar(
        select(MicroAppOperation)
        .where(MicroAppOperation.asset_id == asset.id, MicroAppOperation.action.like("publish:%"))
        .order_by(MicroAppOperation.created_at.desc())
        .limit(1)
    )
    return {
        "asset_id": str(asset.id),
        "slug": asset.slug,
        "title": asset.title,
        # Deferred column: an explicit query, no lazy load in async code.
        "description": await session.scalar(select(Asset.summary).where(Asset.id == asset.id)),
        "environment": env.environment,
        "app_url": app_url(settings, env.asset_hex),
        "owner": {"id": str(owner.id), "display_name": owner.display_name} if owner else None,
        "project": {"id": str(project.id), "name": project.name, "slug": project.slug}
        if project
        else None,
        "desired_state": env.desired_state,
        "generation": env.control_generation,
        "package_version": asset.version,
        "active_release": (
            {
                "id": str(release.id),
                "package_version": release.package_version,
                "digest": release.digest,
                "activated_at": _iso(release.activated_at),
                "schema": [release.schema_min, release.schema_max],
            }
            if release
            else None
        ),
        "last_publication": (
            {
                "operation_id": last_op.id,
                "status": last_op.status,
                "step": last_op.step,
                "error_code": last_op.error_code,
                "at": _iso(last_op.updated_at),
            }
            if last_op and r.control
            else None
        ),
        "runtime": _runtime(env, stats, broker),
        "data": _data(stats, env),
        "rights": r.as_dict(),
        "suspended_at": _iso(env.suspended_at),
    }


async def list_apps(
    session: AsyncSession,
    settings: Settings,
    user: User,
    *,
    q: str | None,
    state: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    stmt = (
        select(Asset, MicroAppEnvironment, MicroAppStats, User, Project)
        .join(MicroAppEnvironment, MicroAppEnvironment.asset_id == Asset.id)
        .outerjoin(MicroAppStats, MicroAppStats.environment_id == MicroAppEnvironment.id)
        .outerjoin(User, User.id == Asset.owner_id)
        .outerjoin(Project, Project.id == Asset.project_id)
        .where(Asset.kind == MICRO_APPLICATION, visible_assets_filter(user))
    )
    if q:
        # The search every other list uses: title, summary and tags.
        stmt = stmt.where(search_filter(q))
    if state == "suspended":
        stmt = stmt.where(MicroAppEnvironment.desired_state == "suspended")
    elif state in ("enabled",):
        stmt = stmt.where(MicroAppEnvironment.desired_state == "enabled")
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        await session.execute(stmt.order_by(Asset.title, Asset.id).offset(offset).limit(limit))
    ).all()
    broker = await broker_incarnation()
    items = [
        await _view(session, settings, user, a, e, s, owner=o, project=p, broker=broker)
        for a, e, s, o, p in rows
    ]
    if state in ("running", "sleeping", "ready"):
        items = [i for i in items if i["runtime"]["state"] == state]
    return {"items": items, "total": total, "offset": offset, "limit": limit}


async def detail(
    session: AsyncSession, settings: Settings, user: User, asset_id: Any
) -> dict[str, Any]:
    asset, env = await load_app(session, asset_id)
    if not (await access.rights(session, user, asset)).use:
        raise NotFoundError("not_found", "micro-application not found")
    stats = await session.get(MicroAppStats, env.id)
    owner = await session.get(User, asset.owner_id)
    project = await session.get(Project, asset.project_id) if asset.project_id else None
    broker = await broker_incarnation()
    view = await _view(
        session, settings, user, asset, env, stats, owner=owner, project=project, broker=broker
    )
    release = (
        await session.get(MicroAppRelease, env.active_release_id) if env.active_release_id else None
    )
    if release:
        m = release.manifest
        view["contract"] = {
            "collections": sorted(m["database"]["collections"]),
            "endpoints": [f"{e['method']} /api{e['path']}" for e in m["endpoints"]],
            "roles": sorted(m["roles"]),
            "permissions": sorted(m["permissions"]),
        }
    return view


async def logs(
    session: AsyncSession, user: User, asset_id: Any, *, cursor: int | None, limit: int
) -> dict[str, Any]:
    asset, _ = await load_app(session, asset_id)
    r = await access.rights(session, user, asset)
    if not r.use:
        raise NotFoundError("not_found", "micro-application not found")
    if not (r.control or r.publish):
        raise AccessDeniedError("control_permission_required", "app.control is required for logs")
    stmt = select(MicroAppLog).where(MicroAppLog.asset_id == asset.id)
    if cursor:
        stmt = stmt.where(MicroAppLog.id < cursor)
    rows = list(await session.scalars(stmt.order_by(MicroAppLog.id.desc()).limit(limit)))
    return {
        "items": [
            {
                "id": x.id,
                "ts": _iso(x.ts),
                "level": x.level,
                "source": x.source,
                "message": x.message,
                "request_id": x.request_id,
                "release_id": x.release_id,
                "fields": x.fields,
            }
            for x in rows
        ],
        "next_cursor": str(rows[-1].id) if len(rows) == limit else None,
    }


async def with_release_states(
    session: AsyncSession, asset: Asset, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Version history rows of an app with the release each package version
    became: the current one is the release that runs (a later package may
    have failed to publish)."""
    states = dict(
        (
            await session.execute(
                select(MicroAppRelease.package_version, MicroAppRelease.status).where(
                    MicroAppRelease.asset_id == asset.id
                )
            )
        ).all()
    )
    return [
        {
            **r,
            "release_status": states.get(r["version"]),
            "is_current": states.get(r["version"]) == "active",
        }
        for r in rows
    ]


async def releases(session: AsyncSession, user: User, asset_id: Any) -> dict[str, Any]:
    """Published history for app.use; candidates, failures and change notes
    only for app.publish."""
    asset, _ = await load_app(session, asset_id)
    r = await access.rights(session, user, asset)
    if not r.use:
        raise NotFoundError("not_found", "micro-application not found")
    stmt = (
        select(MicroAppRelease, AssetVersion)
        .join(AssetVersion, AssetVersion.id == MicroAppRelease.asset_version_id)
        .where(MicroAppRelease.asset_id == asset.id)
        # The history lists a few short fields; manifests can be large.
        .options(defer(MicroAppRelease.manifest), defer(MicroAppRelease.validation))
    )
    if not r.publish:
        stmt = stmt.where(MicroAppRelease.status.in_(("active", "superseded")))
    rows = (await session.execute(stmt.order_by(MicroAppRelease.package_version.desc()))).all()
    out = []
    for rel, ver in rows:
        item: dict[str, Any] = {
            "id": str(rel.id),
            "package_version": rel.package_version,
            "status": rel.status,
            "activated_at": _iso(rel.activated_at),
        }
        if r.publish:
            item.update(
                {
                    "digest": rel.digest,
                    "change_note": ver.change_note,
                    "created_at": _iso(rel.created_at),
                }
            )
        out.append(item)
    return {"items": out}


async def package(
    session: AsyncSession,
    settings: Settings,
    user: User,
    asset_id: Any,
    *,
    version: int | None,
    path: str | None,
) -> dict[str, Any]:
    """Author route: full package of a version, app.publish only."""
    asset, _ = await load_app(session, asset_id)
    r = await access.rights(session, user, asset)
    if not r.use:
        raise NotFoundError("not_found", "micro-application not found")
    if not r.publish:
        raise AccessDeniedError(
            "publish_permission_required", "the package sources are available to publishers only"
        )
    v = version or asset.version
    ver = await session.scalar(
        select(AssetVersion).where(AssetVersion.asset_id == asset.id, AssetVersion.version == v)
    )
    if ver is None:
        raise NotFoundError("version_not_found", "no such package version")
    storage = storage_from_url(settings.storage_url)
    keys = await storage.list_prefix_stats(f"{ver.storage_prefix}/")
    files = [{"path": k.removeprefix(f"{ver.storage_prefix}/"), "size": size} for k, size in keys]
    if path is None:
        return {
            "asset_id": str(asset.id),
            "version": v,
            "entry_path": asset.entry_path,
            "files": sorted(files, key=lambda f: f["path"]),
        }
    if path not in {f["path"] for f in files}:
        raise NotFoundError("file_not_found", "no such file in the package")
    data = await read_all(storage, f"{ver.storage_prefix}/{path}")
    try:
        return {"path": path, "version": v, "content": data.decode("utf-8"), "encoding": "utf-8"}
    except UnicodeDecodeError:
        return {
            "path": path,
            "version": v,
            "content": base64.b64encode(data).decode(),
            "encoding": "base64",
        }
