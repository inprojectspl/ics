"""Due queues in Redis: debounced version events and e-mail / Chat batches.
`ZADD NX` lets the first event of a burst fix the due time. The sweeper claims
due members atomically, so an event arriving after a claim starts a new entry
instead of falling into the gap an arq `_job_id` dedupe would leave.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from redis.asyncio import Redis

from app.config import Settings

from .scripts import LuaScript

Queue = Literal["upd", "mail", "chat"]
BatchQueue = Literal["mail", "chat"]
_MARKER_TTL: Final[int] = 3600

_CLAIM = LuaScript(
    """
local ids = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
for _, m in ipairs(ids) do redis.call('ZREM', KEYS[1], m) end
return ids
"""
)


def due_key(queue: Queue) -> str:
    return f"ntf:due:{queue}"


def _asset_base(asset_id: UUID | str) -> str:
    return f"ntf:asset:{{{asset_id}}}"


def batch_key(uid: UUID | str, queue: BatchQueue) -> str:
    return f"ntf:{{{uid}}}:{queue}"


async def claim(redis: Redis, queue: Queue, *, limit: int = 100) -> list[str]:
    return [str(m) for m in await _CLAIM.run(redis, [due_key(queue)], [time.time(), limit])]


# Version events


async def note_update(
    redis: Redis, asset_id: UUID, version: int, actor_id: UUID | None, settings: Settings
) -> None:
    """Remember the first unreported version and who wrote, then schedule
    one fan-out for the whole burst."""
    base = _asset_base(asset_id)
    pipe = redis.pipeline(transaction=True)
    pipe.set(f"{base}:from", version, nx=True, ex=_MARKER_TTL)
    actor = str(actor_id) if actor_id else "-"
    pipe.sadd(f"{base}:actors", actor)
    pipe.expire(f"{base}:actors", _MARKER_TTL)
    pipe.set(f"{base}:last", actor, ex=_MARKER_TTL)
    pipe.zadd(
        due_key("upd"),
        {str(asset_id): time.time() + settings.notifications_update_debounce_seconds},
        nx=True,
    )
    await pipe.execute()


async def take_update(redis: Redis, asset_id: str) -> tuple[int | None, set[str], str | None]:
    """(first version, all actors, last actor) of a claimed burst."""
    base = _asset_base(asset_id)
    pipe = redis.pipeline(transaction=True)
    pipe.getdel(f"{base}:from")
    pipe.smembers(f"{base}:actors")
    pipe.getdel(f"{base}:last")
    pipe.delete(f"{base}:actors")
    first, actors, last, _ = await pipe.execute()
    return (int(first) if first else None), set(actors or ()), last


# E-mail and Chat batches


def next_digest_at(settings: Settings, now: datetime | None = None) -> float:
    tz = ZoneInfo(settings.notifications_timezone)
    current = (now or datetime.now(tz)).astimezone(tz)
    target = current.replace(
        hour=settings.notifications_digest_hour, minute=0, second=0, microsecond=0
    )
    if target <= current:
        target += timedelta(days=1)
    return target.timestamp()


@dataclass(frozen=True, slots=True)
class BatchItem:
    uid: UUID
    queue: BatchQueue
    entry_id: str
    due_at: float


async def add_to_batches(redis: Redis, items: Sequence[BatchItem], settings: Settings) -> None:
    """Queue entries for their e-mail or Chat batch, all in one round trip."""
    if not items:
        return
    ttl = settings.notifications_retention_days * 86_400
    pipe = redis.pipeline(transaction=False)
    for item in items:
        key = batch_key(item.uid, item.queue)
        pipe.rpush(key, item.entry_id)
        pipe.expire(key, ttl)
        pipe.zadd(due_key(item.queue), {str(item.uid): item.due_at}, nx=True)
    await pipe.execute()


async def take_batch(redis: Redis, uid: str, queue: BatchQueue) -> list[str]:
    key = batch_key(uid, queue)
    pipe = redis.pipeline(transaction=True)
    pipe.lrange(key, 0, -1)
    pipe.delete(key)
    ids, _ = await pipe.execute()
    return [str(i) for i in ids]


async def return_batch(
    redis: Redis, uid: str, queue: BatchQueue, ids: Sequence[str], due_at: float
) -> None:
    """Put a failed batch back in front, to be retried at `due_at`."""
    if not ids:
        return
    key = batch_key(uid, queue)
    pipe = redis.pipeline(transaction=True)
    pipe.lpush(key, *reversed(ids))
    pipe.zadd(due_key(queue), {uid: due_at}, nx=True)
    await pipe.execute()


async def bump_attempts(redis: Redis, uid: str, queue: BatchQueue) -> int:
    key = f"{batch_key(uid, queue)}:attempts"
    pipe = redis.pipeline(transaction=True)
    pipe.incr(key)
    pipe.expire(key, 6 * 3600)
    attempts, _ = await pipe.execute()
    return int(attempts)


async def reset_attempts(redis: Redis, uid: str, queue: BatchQueue) -> None:
    await cast(Awaitable[int], redis.delete(f"{batch_key(uid, queue)}:attempts"))
