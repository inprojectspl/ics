"""Per-user notification inbox in Redis (ADR-0023, section 5). Keys share the
hash tag `{uid}`, so the Lua script may touch all of them in one slot:
`ntf:{uid}:log` (stream), `ntf:{uid}:unread` (sorted set, score = ms),
`ntf:{uid}:ck:<k>` (last entry per collapse key), `ntf:live:{uid}` (pub/sub).
The unread count is `ZCARD` of the unread set; there is no counter to drift.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Iterable, Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Any, Final, cast
from uuid import UUID

import orjson
from redis.asyncio import Redis

from app.config import Settings

from .scripts import LuaScript

_ID = re.compile(r"^\d{1,16}-\d{1,10}$")
COLLAPSE_TTL_SECONDS: Final[int] = 900


def is_entry_id(value: str) -> bool:
    """Guard for ids from clients: `-`, `+` and `(` mean ranges to Redis."""
    return bool(_ID.match(value))


def _base(uid: UUID | str) -> str:
    return f"ntf:{{{uid}}}"


def log_key(uid: UUID | str) -> str:
    return f"{_base(uid)}:log"


def unread_key(uid: UUID | str) -> str:
    return f"{_base(uid)}:unread"


def collapse_key(uid: UUID | str, key: str) -> str:
    return f"{_base(uid)}:ck:{key}"


def live_channel(uid: UUID | str) -> str:
    return f"ntf:live:{uid}"


@dataclass(frozen=True, slots=True)
class Delivery:
    user_id: UUID
    payload: dict[str, Any]
    collapse: str | None = None


@dataclass(frozen=True, slots=True)
class Entry:
    id: str
    payload: dict[str, Any]
    read: bool


_PUSH = LuaScript(resources.files(__package__).joinpath("lua/inbox_push.lua").read_text())


def _min_id(settings: Settings) -> str:
    cutoff_ms = int(time.time() * 1000) - settings.notifications_retention_days * 86_400_000
    return f"{cutoff_ms}-0"


async def push_many(
    redis: Redis, deliveries: Sequence[Delivery], settings: Settings
) -> list[tuple[str, int]]:
    """Append entries for many recipients in one round trip. Returns the new
    entry id and the recipient's unread count, in the order of `deliveries`."""
    if not deliveries:
        return []
    ttl = settings.notifications_retention_days * 86_400
    min_id = _min_id(settings)

    def build(pipe: Any) -> None:
        for d in deliveries:
            _PUSH.queue(
                pipe,
                keys=[
                    log_key(d.user_id),
                    unread_key(d.user_id),
                    collapse_key(d.user_id, d.collapse or "-"),
                ],
                args=[
                    orjson.dumps(d.payload).decode(),
                    settings.notifications_inbox_max,
                    min_id,
                    ttl,
                    COLLAPSE_TTL_SECONDS,
                    "1" if d.collapse else "0",
                ],
            )

    results = await _PUSH.batch(redis, build)
    return [(str(r[0]), int(r[1])) for r in results]


def _decode(rows: Iterable[Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for entry_id, fields in rows:
        raw = fields.get("p")
        if raw:
            out.append((entry_id, orjson.loads(raw)))
    return out


async def _with_read_flags(
    redis: Redis, uid: UUID, rows: list[tuple[str, dict[str, Any]]]
) -> list[Entry]:
    if not rows:
        return []
    scores = await redis.zmscore(unread_key(uid), [r[0] for r in rows])
    return [
        Entry(id=entry_id, payload=payload, read=score is None)
        for (entry_id, payload), score in zip(rows, scores, strict=True)
    ]


async def page(
    redis: Redis, uid: UUID, *, before: str | None, limit: int, unread_only: bool
) -> tuple[list[Entry], str | None]:
    """Newest first. `before` is exclusive; the second value is the cursor
    for the next page, or None at the end."""
    if unread_only:
        # The unread set is bounded by the inbox cap, so reading it whole is
        # cheaper than a second index.
        ids = await redis.zrevrange(unread_key(uid), 0, -1)
        if before:
            ids = [i for i in ids if _older(i, before)]
        ids = ids[: limit + 1]
        rows = await _fetch(redis, uid, ids[:limit])
        entries = [Entry(id=i, payload=p, read=False) for i, p in rows]
        return entries, (ids[limit - 1] if len(ids) > limit else None)
    upper = f"({before}" if before else "+"
    raw = await redis.xrevrange(log_key(uid), max=upper, min="-", count=limit + 1)
    rows = _decode(raw)
    entries = await _with_read_flags(redis, uid, rows[:limit])
    return entries, (rows[limit - 1][0] if len(rows) > limit else None)


def _parse(entry_id: str) -> tuple[int, int]:
    ms, _, seq = entry_id.partition("-")
    return int(ms), int(seq or 0)


def _older(a: str, b: str) -> bool:
    return _parse(a) < _parse(b)


async def _fetch(redis: Redis, uid: UUID, ids: Sequence[str]) -> list[tuple[str, dict[str, Any]]]:
    if not ids:
        return []
    pipe = redis.pipeline(transaction=False)
    for entry_id in ids:
        pipe.xrange(log_key(uid), min=entry_id, max=entry_id)
    out: list[tuple[str, dict[str, Any]]] = []
    for rows in await pipe.execute():
        out.extend(_decode(rows))
    return out


async def get_many(redis: Redis, uid: UUID, ids: Sequence[str]) -> list[Entry]:
    """Entries that still exist, with read flags; used by the batch senders."""
    return await _with_read_flags(redis, uid, await _fetch(redis, uid, ids))


async def since(redis: Redis, uid: UUID, last_id: str, *, limit: int = 200) -> list[Entry] | None:
    """Entries after `last_id`, oldest first, for an SSE resume. None when
    the client is too far behind (it refetches instead)."""
    raw = await redis.xrange(log_key(uid), min=f"({last_id}", max="+", count=limit + 1)
    rows = _decode(raw)
    if len(rows) > limit:
        return None
    return await _with_read_flags(redis, uid, rows)


async def unread_count(redis: Redis, uid: UUID) -> int:
    return int(await redis.zcard(unread_key(uid)))


async def mark_read(redis: Redis, uid: UUID, ids: Sequence[str]) -> int:
    pipe = redis.pipeline(transaction=True)
    if ids:
        pipe.zrem(unread_key(uid), *ids)
    pipe.zcard(unread_key(uid))
    return int((await pipe.execute())[-1])


async def mark_all_read(redis: Redis, uid: UUID) -> None:
    await redis.delete(unread_key(uid))


async def mark_unread(redis: Redis, uid: UUID, ids: Sequence[str]) -> tuple[list[str], int]:
    """Only ids still in the log become unread again."""
    existing = [entry_id for entry_id, _ in await _fetch(redis, uid, ids)]
    pipe = redis.pipeline(transaction=True)
    if existing:
        pipe.zadd(unread_key(uid), {i: _parse(i)[0] for i in existing})
    pipe.zcard(unread_key(uid))
    return existing, int((await pipe.execute())[-1])


async def delete(redis: Redis, uid: UUID, entry_id: str) -> int | None:
    """Unread count after the delete, or None when the entry does not exist."""
    pipe = redis.pipeline(transaction=True)
    pipe.xdel(log_key(uid), entry_id)
    pipe.zrem(unread_key(uid), entry_id)
    pipe.zcard(unread_key(uid))
    removed, _, count = await pipe.execute()
    return int(count) if removed else None


async def clear(redis: Redis, uid: UUID) -> None:
    await redis.delete(log_key(uid), unread_key(uid))


def live_message(event: str, data: dict[str, Any], *, entry_id: str = "") -> bytes:
    """Wire format on `ntf:live:{uid}`, read by `live.py`."""
    return orjson.dumps({"e": event, "id": entry_id, "d": data})


async def publish(
    redis: Redis, uid: UUID, event: str, data: dict[str, Any], *, entry_id: str = ""
) -> None:
    message = live_message(event, data, entry_id=entry_id)
    await cast(Awaitable[int], redis.publish(live_channel(uid), message))
