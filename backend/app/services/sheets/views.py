"""What a person sees of a link and its syncs, and the access request
(ADR-0031, ADR-0033)."""

from __future__ import annotations

from collections.abc import Callable
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
from app.models import SheetOperation, User
from app.redis_client import get_redis
from app.services.notifications import preferences
from app.services.notifications.fanout import notify_user
from app.services.notifications.items import AssetRef, build_payload
from app.services.versions import author_label

from . import grants, links
from .common import operation, placer, row_limit, runnable_link

# ------------------------------------------------------------------- views


def _where(
    place: Callable[[int], list[int]], titles: dict[int, str]
) -> Callable[[int | None], dict[str, Any]]:
    """The tab and the tab's own row of a row a preview part counts across
    its tabs, as an item of a view carries them."""

    def where(row: int | None) -> dict[str, Any]:
        if row is None:
            return {}
        sheet_id, own = place(row)
        return {"tab": titles[sheet_id], "row": own}

    return where


def _details(op: SheetOperation) -> dict[str, Any]:
    """The changes of every mapping as flat lists, each item naming its
    collection, tab and the row in that tab."""
    out: dict[str, Any] = {"headers": {}, "updates": [], "creates": [], "appends": [], "issues": []}
    for part in (op.preview.get("mappings") or {}).values():
        coll = part["collection"]
        titles = {t["sheet_id"]: t["title"] for t in part["sheet"]["tabs"]}
        where = _where(placer(part), titles)

        out["headers"][coll] = part.get("headers") or {}
        out["updates"] += [
            {
                "collection": coll,
                "record_id": u["record_id"],
                **where(u["row"]),
                **{k: u[k] for k in ("import", "export", "conflicts")},
            }
            for u in part["updates"]
        ]
        out["creates"] += [
            {"collection": coll, "record_id": c["record_id"], **where(c["row"]), "data": c["data"]}
            for c in part["creates"]
        ]
        out["appends"] += [
            {
                "collection": coll,
                "record_id": a["record_id"],
                "tab": titles.get(a.get("sheet_id")),
                "values": a["values"],
            }
            for a in part["appends"]
        ]
        for issue in part["issues"]:
            item = {**issue, "collection": coll, **where(issue.get("row"))}
            if "first_row" in issue:
                first = where(issue["first_row"])
                item["first_row"], item["first_tab"] = first["row"], first["tab"]
            out["issues"].append(item)
    return out


def op_view(op: SheetOperation, user: User, *, detail: bool = True) -> dict[str, Any]:
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
        # Its sheet write is not known to have landed: check it before the
        # next sync of the file.
        "unsettled": op.state == "applied" and op.google_status in links.UNSETTLED,
    }
    if mine and detail and op.preview:
        out.update(_details(op))
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
    out["link"] = links.view(link, await links.mappings_of(session, link))
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
    views = [op_view(op, user, detail=False) for op in ops]
    if ops and ops[0].actor_id == user.id and _unfinished(ops[0]):
        await session.refresh(ops[0], ["preview"])
        views[0] = op_view(ops[0], user)
    out["operations"] = views
    return out


async def get_operation(
    session: AsyncSession, user: User, asset_id: UUID, op_id: UUID
) -> dict[str, Any]:
    _, _, rights = await links.rights_for(session, user, asset_id)
    if not rights.control:
        raise AccessDeniedError("forbidden", "the sync needs the app.control right")
    link = await links.require(session, asset_id)
    return op_view(await operation(session, link, op_id), user)


ACCESS_REQUEST_TTL = 3600


async def request_access(
    session: AsyncSession, settings: Settings, user: User, asset_id: UUID
) -> dict[str, Any]:
    """Ask the asset's owner, in their ICS inbox, to share the spreadsheet
    with this person's Google account. Grants nothing: Google still decides,
    and the person checks again with a new preview. One request an hour."""
    asset, link, _, _ = await runnable_link(session, user, asset_id)
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
