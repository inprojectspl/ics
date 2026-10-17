"""Live notification stream over Server-Sent Events (ADR-0023, section 6)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, session_store
from app.auth import CurrentUser
from app.db import get_session
from app.errors import ApiError
from app.redis_client import get_redis
from app.services.notifications import inbox
from app.services.notifications.items import to_item
from app.services.notifications.live import OVERFLOW, get_hub

from ._router import router

_WAIT_SECONDS = 30.0
_REVOCATION_CHECK_SECONDS = 60.0
# A stream ends after this long; the browser reconnects with `Last-Event-ID`
# and misses nothing. Spreads long-lived connections over processes again
# after a deploy and bounds how long a stale process keeps a tab.
_MAX_STREAM_SECONDS = 15 * 60
_BROWSER_TRANSPORTS = frozenset({"cookie", "dev_stub"})


def _event(message: dict[str, Any]) -> ServerSentEvent:
    return ServerSentEvent(event=message["e"], id=message.get("id") or None, data=message["d"])


@dataclass(frozen=True, slots=True)
class _Viewer:
    uid: UUID
    sid: str | None


async def _browser_viewer(
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> _Viewer:
    """Checks run here, before the stream starts: an error raised inside the
    generator would come after the 200 is already sent."""
    if audit.request_transport(request) not in _BROWSER_TRANSPORTS:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, "stream_browser_only", "the stream needs a browser session"
        )
    viewer = _Viewer(uid=user.id, sid=request.session.get(session_store.SESSION_SID_KEY))
    # The request session would otherwise hold a pool connection for as long
    # as the tab stays open.
    await session.close()
    return viewer


@router.get("/stream", response_class=EventSourceResponse)
async def notification_stream(
    viewer: Annotated[_Viewer, Depends(_browser_viewer)],
    last_event_id: Annotated[str | None, Header(max_length=40)] = None,
) -> AsyncIterator[ServerSentEvent]:
    uid, sid = viewer.uid, viewer.sid
    redis = get_redis()
    hub = get_hub()
    queue = await hub.subscribe(uid)
    try:
        unread = await inbox.unread_count(redis, uid)
        if last_event_id and inbox.is_entry_id(last_event_id):
            missed = await inbox.since(redis, uid, last_event_id)
            if missed is None:
                yield ServerSentEvent(event="reset", data={})
            for entry in missed or []:
                item = to_item(entry)
                yield ServerSentEvent(
                    event="notification", id=entry.id, data={"item": item, "unread": unread}
                )
        yield ServerSentEvent(event="sync", data={"unread": unread})
        next_check = time.monotonic() + _REVOCATION_CHECK_SECONDS
        ends_at = time.monotonic() + _MAX_STREAM_SECONDS
        while time.monotonic() < ends_at:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=_WAIT_SECONDS)
            except TimeoutError:
                message = None
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + _REVOCATION_CHECK_SECONDS
                if sid and await session_store.is_revoked(redis, sid):
                    return
            if message is None:
                continue
            if message is OVERFLOW:
                yield ServerSentEvent(event="reset", data={})
                return
            yield _event(message)
    finally:
        await hub.unsubscribe(uid, queue)
