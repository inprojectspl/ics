"""Reading and tidying the caller's inbox."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import get_session
from app.errors import ApiError
from app.models import Asset, User
from app.permissions import visible_assets_filter
from app.redis_client import get_redis
from app.services.notifications import inbox
from app.services.notifications.items import to_item

from ._router import router

_MAX_IDS = 200


class IdsIn(BaseModel):
    ids: list[str] | None = Field(default=None, max_length=_MAX_IDS)
    all: bool = False


class UnreadIn(BaseModel):
    ids: list[str] = Field(max_length=_MAX_IDS)


def _clean(ids: list[str] | None) -> list[str]:
    return [i for i in (ids or []) if inbox.is_entry_id(i)]


async def _visible_ids(session: AsyncSession, user: User, entries: list[inbox.Entry]) -> set[str]:
    """Asset ids on the page the caller can still read. One query per page:
    access is checked again when reading, not only at delivery."""
    asset_ids = {e.payload["as"] for e in entries if e.payload.get("as")}
    if not asset_ids:
        return set()
    rows = await session.scalars(
        select(Asset.id).where(Asset.id.in_(asset_ids), visible_assets_filter(user))
    )
    return {str(a) for a in rows}


def _is_unavailable(entry: inbox.Entry, visible: set[str]) -> bool:
    asset_id = entry.payload.get("as")
    # A deletion notice stays readable: it is about an asset that is gone.
    if not asset_id or entry.payload.get("c") == "asset.deleted":
        return False
    return asset_id not in visible


@router.get("")
async def list_notifications(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    before: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
    unread: bool = False,
) -> dict[str, Any]:
    if before is not None and not inbox.is_entry_id(before):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid cursor")
    entries, next_cursor = await inbox.page(
        get_redis(), user.id, before=before, limit=limit, unread_only=unread
    )
    visible = await _visible_ids(session, user, entries)
    return {
        "items": [to_item(e, unavailable=_is_unavailable(e, visible)) for e in entries],
        "next": next_cursor,
    }


@router.get("/summary")
async def notification_summary(user: CurrentUser) -> dict[str, int]:
    return {"unread": await inbox.unread_count(get_redis(), user.id)}


@router.post("/read")
async def mark_read(body: IdsIn, user: CurrentUser) -> dict[str, int]:
    redis = get_redis()
    if body.all:
        await inbox.mark_all_read(redis, user.id)
        await inbox.publish(redis, user.id, "sync", {"unread": 0, "all_read": True})
        return {"unread": 0}
    ids = _clean(body.ids)
    count = await inbox.mark_read(redis, user.id, ids)
    await inbox.publish(redis, user.id, "sync", {"unread": count, "read": ids})
    return {"unread": count}


@router.post("/unread")
async def mark_unread(body: UnreadIn, user: CurrentUser) -> dict[str, int]:
    redis = get_redis()
    ids, count = await inbox.mark_unread(redis, user.id, _clean(body.ids))
    await inbox.publish(redis, user.id, "sync", {"unread": count, "unread_ids": ids})
    return {"unread": count}


@router.delete("")
async def clear_notifications(user: CurrentUser) -> dict[str, int]:
    redis = get_redis()
    await inbox.clear(redis, user.id)
    await inbox.publish(redis, user.id, "sync", {"unread": 0, "cleared": True})
    return {"unread": 0}


@router.delete("/{entry_id}")
async def delete_notification(entry_id: str, user: CurrentUser) -> dict[str, int]:
    redis = get_redis()
    count = await inbox.delete(redis, user.id, entry_id) if inbox.is_entry_id(entry_id) else None
    if count is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "notification_not_found", "notification not found"
        )
    await inbox.publish(redis, user.id, "sync", {"unread": count, "deleted": [entry_id]})
    return {"unread": count}
