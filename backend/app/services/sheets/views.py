"""What a person sees of a link and its syncs, and the access request (ADR-0031)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app import audit
from app.config import Settings
from app.domain_errors import (
    AccessDeniedError,
    ConflictError,
)
from app.models import SheetLink, SheetOperation, User
from app.redis_client import get_redis
from app.services.notifications import preferences
from app.services.notifications.fanout import notify_user
from app.services.notifications.items import AssetRef, build_payload
from app.services.versions import author_label

from . import grants, links
from .common import operation, row_limit, runnable_link

# ------------------------------------------------------------------- views


def op_view(
    op: SheetOperation, link: SheetLink, user: User, *, detail: bool = True
) -> dict[str, Any]:
    """An operation; its changes only for the person who made it (values come
    from records that person could read) and only when asked for."""
    mine = op.actor_id == user.id
    out: dict[str, Any] = {
        "id": str(op.id),
        "state": op.state,
        "google_status": op.google_status,
        "error": op.error,
        "mine": mine,
        "created_at": op.created_at.isoformat() if op.created_at else None,
        "summary": op.summary,
        "result": op.result,
        "auto": op.auto,
    }
    if mine and detail and op.preview:
        out["headers"] = {c["field"]: c["header"] for c in link.columns}
        out["updates"] = [
            {k: u[k] for k in ("record_id", "row", "import", "export", "conflicts")}
            for u in op.preview["updates"]
        ]
        out["creates"] = op.preview["creates"]
        out["appends"] = op.preview["appends"]
        out["issues"] = op.preview["issues"]
        if op.decisions:
            out["decisions"] = op.decisions
    return out


def _unfinished(op: SheetOperation) -> bool:
    return op.state in ("previewed", "applying") or op.google_status in ("pending", "uncertain")


async def status(
    session: AsyncSession, settings: Settings, user: User, asset_id: UUID
) -> dict[str, Any]:
    asset, _, rights = await links.rights_for(session, user, asset_id)
    link = await links.get(session, asset_id)
    me = await grants.grant_of(session, user.id)
    out: dict[str, Any] = {
        "enabled": grants.enabled(settings),
        "rights": {
            "configure": rights.manage,
            "run": rights.control,
            "owner": asset.owner_id == user.id,
        },
        "my_google": {"email": me.email} if me else None,
        "link": None,
        "operations": [],
    }
    out["row_limit"] = await row_limit(session, settings, asset)
    out["auto_interval_seconds"] = settings.google_sheets_poll_seconds
    out["auto_active_interval_seconds"] = settings.google_sheets_active_poll_seconds
    if link is None:
        return out
    out["link"] = links.view(link)
    if link.account_mode == "owner_account":
        out["owner_google_connected"] = await grants.grant_of(session, asset.owner_id) is not None
    if not rights.control:
        return out
    # The history needs states and counts only; the newest operation keeps its
    # changes when it is the caller's and still unfinished, to resume it.
    ops = list(
        await session.scalars(
            select(SheetOperation)
            .options(defer(SheetOperation.preview), defer(SheetOperation.export))
            .where(SheetOperation.link_id == link.id)
            .order_by(SheetOperation.created_at.desc())
            .limit(10)
        )
    )
    views = [op_view(op, link, user, detail=False) for op in ops]
    if ops and ops[0].actor_id == user.id and _unfinished(ops[0]):
        await session.refresh(ops[0], ["preview"])
        views[0] = op_view(ops[0], link, user)
    out["operations"] = views
    return out


async def get_operation(
    session: AsyncSession, user: User, asset_id: UUID, op_id: UUID
) -> dict[str, Any]:
    _, _, rights = await links.rights_for(session, user, asset_id)
    if not rights.control:
        raise AccessDeniedError("forbidden", "the sync needs the app.control right")
    link = await links.require(session, asset_id)
    return op_view(await operation(session, link, op_id), link, user)


ACCESS_REQUEST_TTL = 3600


async def request_access(
    session: AsyncSession, settings: Settings, user: User, asset_id: UUID
) -> dict[str, Any]:
    """Ask the asset's owner, in their ICS inbox, to share the spreadsheet
    with this person's Google account. Grants nothing: Google still decides,
    and the person checks again with a new preview. One request an hour."""
    asset, link, _ = await runnable_link(session, user, asset_id)
    if link.account_mode != "per_user":
        raise ConflictError("access_request_not_needed", "the sync uses the owner's Google account")
    if asset.owner_id == user.id:
        raise ConflictError("access_request_not_needed", "you own the application")
    grant = await grants.grant_of(session, user.id)
    if grant is None:
        raise ConflictError(
            "google_not_connected",
            "connect your Google account first",
            extra={"action": "connect_google"},
        )
    owner = await session.get(User, asset.owner_id)
    if owner is None or owner.is_locked:
        raise ConflictError("owner_unavailable", "the application's owner cannot be reached")
    fresh = await get_redis().set(
        f"sheets:access:{link.id}:{user.id}", "1", nx=True, ex=ACCESS_REQUEST_TTL
    )
    if not fresh:
        return {"sent": False, "reason": "already_requested"}
    payload = build_payload(
        "sheets.access_requested",
        asset=AssetRef(
            id=str(asset.id), slug=asset.slug, title=asset.title or asset.slug, kind=asset.kind
        ),
        project=None,
        actor_id=str(user.id),
        actor_name=author_label(user.display_name, user.email),
        params={"email": grant.email},
    )
    prefs = await preferences.load(session, owner.id)
    await notify_user(get_redis(), settings, owner, prefs, payload)
    await audit.record(session, actor=user, action="sheet_access_requested", target=str(asset.id))
    await session.commit()
    return {"sent": True}
