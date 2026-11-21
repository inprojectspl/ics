"""What the broker may ask ICS (private network, service token): authorize a
request, exchange a launch code, fetch an active release's files and the
runtime database credential, and report measurements and logs."""

from __future__ import annotations

import json
import secrets
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import quota, secret_box
from app.config import Settings
from app.domain_errors import InvalidInputError, NotFoundError
from app.models import (
    Asset,
    AssetVersion,
    MicroAppEnvironment,
    MicroAppLog,
    MicroAppRelease,
    MicroAppSchemaBinding,
    MicroAppStats,
    ShareLink,
    User,
)
from app.redis_client import get_redis
from app.services.micro_applications import access
from app.services.micro_applications.common import ENVIRONMENT
from app.services.micro_applications.hosts import env_for_host
from app.services.micro_applications.publish import SECRET_PURPOSE
from app.storage import read_all, storage_from_url

LAUNCH_TTL_S = 60
_HEX = frozenset("0123456789abcdef")


def _check_hex(asset_hex: str) -> None:
    if len(asset_hex) != 32 or not set(asset_hex) <= _HEX:
        raise NotFoundError("not_found", "unknown application")


async def _env_by_hex(
    session: AsyncSession, asset_hex: str, environment: str
) -> MicroAppEnvironment:
    _check_hex(asset_hex)
    env = await session.scalar(
        select(MicroAppEnvironment).where(
            MicroAppEnvironment.asset_hex == asset_hex,
            MicroAppEnvironment.environment == environment,
        )
    )
    if env is None:
        raise NotFoundError("not_found", "unknown application")
    return env


def _share_admits(share: ShareLink | None, asset: Asset) -> bool:
    """A share session stays valid while its link is neither revoked nor
    expired. The view budget counts launches, not requests."""
    if share is None or share.asset_id != asset.id or share.revoked_at is not None:
        return False
    return share.expires_at is None or share.expires_at > datetime.now(UTC)


async def authorize(
    session: AsyncSession,
    asset_hex: str,
    environment: str,
    user_id: UUID | None,
    share_id: UUID | None = None,
    share_token: str | None = None,
) -> dict[str, Any]:
    """What the broker session may do now. `share_token` is the link named in
    a page address (`ics_share`): `share_token_id` says which live link of
    this app it is, so the broker can tell a visit of another link apart."""
    env = await _env_by_hex(session, asset_hex, environment)
    asset = await session.get(Asset, env.asset_id)
    if asset is None:
        return {"found": False}
    release = await access.active_release(session, env)
    user_out: dict[str, Any] | None = None
    grants: Collection[str] = ()
    if share_id is not None:
        # A visitor who came through a share link: an anonymous identity of
        # the broker session, with exactly the link's app permissions.
        share = await session.get(ShareLink, share_id)
        if user_id is not None and share is not None and _share_admits(share, asset):
            user_out = {"id": str(user_id), "display_name": None, "email": None, "guest": True}
            grants = share.app_permissions or ()
    else:
        user = await session.get(User, user_id) if user_id else None
        rights = await access.rights(session, user, asset) if user is not None else None
        if user is not None and rights is not None and rights.use:
            user_out = {
                "id": str(user.id),
                "display_name": user.display_name,
                "email": user.email,
                "guest": False,
            }
            grants = rights.grants
    binding = await session.scalar(
        select(MicroAppSchemaBinding).where(MicroAppSchemaBinding.environment_id == env.id)
    )
    data_full = await quota.owner_data_full(asset.owner_id)
    named = (
        await session.scalar(select(ShareLink).where(ShareLink.token == share_token))
        if share_token
        else None
    )
    return {
        "found": True,
        "asset_id": str(asset.id),
        "slug": asset.slug,
        "title": asset.title,
        "deleted": asset.deleted_at is not None,
        "desired_state": env.desired_state,
        "release": {"id": str(release.id), "digest": release.digest} if release else None,
        "data_generation": env.data_generation,
        "policy_generation": env.policy_generation,
        "control_generation": env.control_generation,
        "credential_generation": binding.credential_generation if binding else None,
        "app_use": user_out is not None,
        "user": user_out,
        "permissions": sorted(access.expand(grants, release)),
        "roles": access.held_roles(grants, release),
        "data_quota": {"exceeded": data_full},
        "share_token_id": str(named.id) if named and _share_admits(named, asset) else None,
    }


async def _store_launch_code(
    env: MicroAppEnvironment, host: str, state: str, *, user_id: str | None, share_id: str | None
) -> str:
    if not state or len(state) > 128:
        raise InvalidInputError("launch_invalid", "missing launch state", field="state")
    code = secrets.token_urlsafe(32)
    payload = {
        "user_id": user_id,
        "share_id": share_id,
        "asset_hex": env.asset_hex,
        "environment": ENVIRONMENT,
        "host": host.lower(),
        "state": state,
    }
    await get_redis().set(f"microapp:launch:{code}", json.dumps(payload), ex=LAUNCH_TTL_S)
    return code


async def issue_share_launch_code(
    session: AsyncSession, settings: Settings, share: ShareLink, host: str, state: str
) -> str:
    """One-time code for a share-link visit of exactly this app host and
    browser start; the link's gate was checked by the caller."""
    env = await env_for_host(session, settings, host)
    if env.asset_id != share.asset_id:
        raise NotFoundError("not_found", "unknown application")
    return await _store_launch_code(env, host, state, user_id=None, share_id=str(share.id))


async def issue_launch_code(
    session: AsyncSession, settings: Settings, user: User, host: str, state: str
) -> str:
    """One-time code for exactly this user, app, host and browser start."""
    env = await env_for_host(session, settings, host)
    asset = await session.get(Asset, env.asset_id)
    if asset is None or not (await access.rights(session, user, asset)).use:
        raise NotFoundError("not_found", "unknown application")
    return await _store_launch_code(env, host, state, user_id=str(user.id), share_id=None)


async def exchange_launch_code(code: str, host: str, state: str) -> dict[str, Any]:
    raw = await get_redis().getdel(f"microapp:launch:{code}") if code else None
    if raw is None:
        raise InvalidInputError("launch_invalid", "the launch code is invalid or expired")
    data = json.loads(raw)
    if data["host"] != host.lower() or not secrets.compare_digest(data["state"], state or ""):
        raise InvalidInputError("launch_invalid", "the launch code belongs to another start")
    return {
        "user_id": data["user_id"],
        "asset_hex": data["asset_hex"],
        "environment": data["environment"],
        "share_id": data.get("share_id"),
    }


async def _release_tree(
    session: AsyncSession, release_id: UUID
) -> tuple[MicroAppRelease, AssetVersion, MicroAppEnvironment]:
    release = await session.get(MicroAppRelease, release_id)
    if release is None or release.status not in ("active", "superseded"):
        raise NotFoundError("not_found", "release not found")
    version = await session.get(AssetVersion, release.asset_version_id)
    env = await session.scalar(
        select(MicroAppEnvironment).where(MicroAppEnvironment.asset_id == release.asset_id)
    )
    if version is None or env is None:
        raise NotFoundError("not_found", "release not found")
    return release, version, env


async def bundle(session: AsyncSession, settings: Settings, release_id: UUID) -> dict[str, Any]:
    from app.services.micro_applications.provisioning import Names

    release, version, env = await _release_tree(session, release_id)
    storage = storage_from_url(settings.storage_url)
    keys = await storage.list_prefix(f"{version.storage_prefix}/")
    rel_paths = [k.removeprefix(f"{version.storage_prefix}/") for k in keys]
    handlers = {}
    for path in rel_paths:
        if path.startswith("handlers/") and path.endswith(".mjs"):
            handlers[path] = (await read_all(storage, f"{version.storage_prefix}/{path}")).decode()
    return {
        "release_id": str(release.id),
        "digest": release.digest,
        "manifest": release.manifest,
        "schema": Names.for_asset(env.asset_hex, env.environment).schema,
        "handlers": handlers,
        "public_files": sorted(p for p in rel_paths if p.startswith("public/")),
    }


async def public_file(
    session: AsyncSession, settings: Settings, release_id: UUID, path: str
) -> bytes | None:
    if not path.startswith("public/") or ".." in path.split("/"):
        return None
    _, version, _ = await _release_tree(session, release_id)
    storage = storage_from_url(settings.storage_url)
    try:
        return await read_all(storage, f"{version.storage_prefix}/{path}")
    except FileNotFoundError:
        return None


async def binding(
    session: AsyncSession, settings: Settings, asset_id: UUID, environment: str
) -> dict[str, Any]:
    env = await session.scalar(
        select(MicroAppEnvironment).where(
            MicroAppEnvironment.asset_id == asset_id, MicroAppEnvironment.environment == environment
        )
    )
    b = (
        await session.scalar(
            select(MicroAppSchemaBinding).where(MicroAppSchemaBinding.environment_id == env.id)
        )
        if env
        else None
    )
    if b is None or b.provisioned_at is None:
        raise NotFoundError("not_found", "no database binding")
    password = secret_box.decrypt(settings, SECRET_PURPOSE, b.secret_ciphertext)
    if password is None:
        raise NotFoundError("not_found", "binding secret unreadable")
    return {
        "asset_id": str(asset_id),
        "environment": environment,
        "host": settings.microapps_runtime_db_host,
        "port": settings.microapps_runtime_db_port,
        "database": b.database,
        "schema": b.schema_name,
        "user": b.runtime_role,
        "password": password,
        "credential_generation": b.credential_generation,
    }


def _ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


BROKER_HEARTBEAT_KEY = "microapp:broker:heartbeat"


async def report(session: AsyncSession, payload: dict[str, Any]) -> dict[str, int]:
    now = datetime.now(UTC)
    # Which broker process is alive now: a sample from an older incarnation
    # describes a context that no longer exists.
    await get_redis().set(
        BROKER_HEARTBEAT_KEY,
        json.dumps(
            {"incarnation": str(payload.get("incarnation", ""))[:64], "at": now.isoformat()}
        ),
        ex=60,
    )
    apps = payload.get("apps") or []
    by_asset: dict[str, dict[str, Any]] = {
        str(a.get("asset_id")): a for a in apps if a.get("asset_id")
    }
    envs = (
        list(
            await session.scalars(
                select(MicroAppEnvironment).where(
                    MicroAppEnvironment.asset_id.in_([UUID(k) for k in by_asset])
                )
            )
        )
        if by_asset
        else []
    )
    for env in envs:
        a = by_asset[str(env.asset_id)]
        values = {
            "environment_id": env.id,
            "runtime_state": str(a.get("state", "unknown"))[:16],
            "runtime_sampled_at": now,
            "broker_incarnation": str(payload.get("incarnation", ""))[:64],
            "inflight": int(a.get("inflight") or 0),
            "queued": int(a.get("queued") or 0),
            "open_connections": int(a.get("open_connections") or 0),
            "last_used_at": _ts(a.get("last_used_at")),
            "last_error_code": (
                str(a["last_error_code"])[:64] if a.get("last_error_code") else None
            ),
            "last_error_at": _ts(a.get("last_error_at")),
            "breaker_open_until": _ts(a.get("breaker_open_until")),
        }
        stmt = insert(MicroAppStats).values(**values)
        update_cols = {k: stmt.excluded[k] for k in values if k != "environment_id"}
        await session.execute(
            stmt.on_conflict_do_update(index_elements=["environment_id"], set_=update_cols)
        )
    log_ids = set()
    for line in (payload.get("logs") or [])[:500]:
        try:
            log_ids.add(UUID(str(line.get("asset_id"))))
        except ValueError:
            continue
    known_ids = (
        {
            str(x)
            for x in await session.scalars(
                select(MicroAppEnvironment.asset_id).where(
                    MicroAppEnvironment.asset_id.in_(log_ids)
                )
            )
        }
        if log_ids
        else set()
    )
    stored = 0
    for line in (payload.get("logs") or [])[:500]:
        aid = str(line.get("asset_id"))
        if aid not in known_ids:
            continue
        fields = line.get("fields") if isinstance(line.get("fields"), dict) else {}
        if len(json.dumps(fields, default=str)) > 2000:
            fields = {"truncated": True}
        session.add(
            MicroAppLog(
                asset_id=UUID(aid),
                environment=str(line.get("environment") or ENVIRONMENT)[:16],
                ts=_ts(line.get("ts")) or now,
                level=str(line.get("level") or "info")[:8],
                source=str(line.get("source") or "runtime")[:16],
                request_id=(str(line["request_id"])[:64] if line.get("request_id") else None),
                release_id=(str(line["release_id"])[:64] if line.get("release_id") else None),
                message=str(line.get("message") or "")[:1000],
                fields=fields,
            )
        )
        stored += 1
    await session.commit()
    return {"apps": len(envs), "logs": stored}
