"""Arq tasks of notifications (ADR-0023). The logic is in
`services.notifications`; these wrappers bind the worker's session factory
and keep one failing recipient or asset from blocking the rest."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from uuid import UUID

from app.config import get_settings
from app.db import SessionLocal
from app.models import Asset
from app.redis_client import get_redis
from app.services.notifications import batches, fanout, schedule
from app.services.notifications.items import EVENT_KINDS, EventKind

logger = logging.getLogger("ics.notifications.jobs")

_KINDS: dict[str, EventKind] = {k: k for k in EVENT_KINDS}
_SENDERS = {"mail": batches.send_mail, "chat": batches.send_chat}
# Claimed work runs concurrently, each item on its own session.
_CONCURRENCY = 8


def _uuid(value: str | None) -> UUID | None:
    return UUID(value) if value and value != "-" else None


async def notify_asset_event(
    ctx: dict, code: str, asset_id: str, actor_id: str | None, project_id: str | None
) -> int:
    kind = _KINDS.get(code)
    if kind is None:
        logger.warning("unknown notification code %r", code)
        return 0
    actor = _uuid(actor_id)
    async with SessionLocal() as session:
        return await fanout.fan_out(
            session,
            get_redis(),
            get_settings(),
            code=kind,
            asset_id=UUID(asset_id),
            actor_id=actor,
            excluded={actor} if actor else set(),
            project_id=_uuid(project_id),
        )


async def _updated(asset_id: str) -> None:
    redis = get_redis()
    first, actors, last = await schedule.take_update(redis, asset_id)
    async with SessionLocal() as session:
        asset = await session.get(Asset, UUID(asset_id))
        if asset is None or asset.deleted_at is not None:
            return
        last_id = _uuid(last)
        actor_ids = {u for u in (_uuid(a) for a in actors) if u is not None}
        # With several writers in one burst each of them hears about the
        # others, and is told who they were rather than only the last one.
        several = len(actors) > 1
        await fanout.fan_out(
            session,
            redis,
            get_settings(),
            code="asset.updated",
            asset_id=asset.id,
            actor_id=last_id,
            excluded=set() if several else actor_ids,
            version=asset.version,
            from_version=min(first or asset.version, asset.version),
            co_actors=sorted(actor_ids, key=lambda u: (u != last_id, str(u))) if several else (),
        )


async def notifications_sweeper(ctx: dict) -> dict:
    """Every 5 s: debounced version events, then due e-mail and Chat batches."""
    redis = get_redis()
    settings = get_settings()
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def guarded(label: str, member: str, work: Callable[[], Awaitable[object]]) -> bool:
        async with semaphore:
            try:
                await work()
                return True
            except Exception:
                logger.exception("notify.%s failed id=%s", label, member)
                return False

    async def send(queue: schedule.BatchQueue, uid: str) -> None:
        async with SessionLocal() as session:
            await _SENDERS[queue](session, redis, settings, uid)

    async def run_all(label: str, members: list[str], work: Callable[[str], Awaitable[object]]):
        results = await asyncio.gather(*(guarded(label, m, partial(work, m)) for m in members))
        return sum(results)

    updated, mail, chat = await asyncio.gather(
        run_all("updated", await schedule.claim(redis, "upd"), _updated),
        run_all("mail", await schedule.claim(redis, "mail"), partial(send, "mail")),
        run_all("chat", await schedule.claim(redis, "chat"), partial(send, "chat")),
    )
    return {"updated": updated, "mail": mail, "chat": chat}
