"""Redis inbox (ADR-0023, section 5): collapse, trimming, unread consistency."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.config import get_settings
from app.redis_client import get_redis
from app.services.notifications import inbox
from app.services.notifications.inbox import Delivery
from app.services.notifications.live import OVERFLOW, LiveHub


def _payload(n: int = 1, v: int = 1, fv: int | None = None) -> dict:
    p = {"c": "asset.updated", "as": "a1", "sl": "s1", "t": "Doc", "k": "md_single", "n": n, "v": v}
    if fv is not None:
        p["fv"] = fv
    return p


async def test_push_and_page_newest_first():
    redis, uid = get_redis(), uuid4()
    settings = get_settings()
    for i in range(3):
        await inbox.push_many(
            redis, [Delivery(uid, {"c": "asset.created", "t": f"d{i}"})], settings
        )
    entries, nxt = await inbox.page(redis, uid, before=None, limit=2, unread_only=False)
    assert [e.payload["t"] for e in entries] == ["d2", "d1"]
    assert nxt == entries[-1].id
    rest, end = await inbox.page(redis, uid, before=nxt, limit=2, unread_only=False)
    assert [e.payload["t"] for e in rest] == ["d0"]
    assert end is None
    assert await inbox.unread_count(redis, uid) == 3


async def test_collapse_merges_unread_entry_and_keeps_first_version():
    redis, uid = get_redis(), uuid4()
    settings = get_settings()
    await inbox.push_many(redis, [Delivery(uid, _payload(v=3), "asset.updated:a1")], settings)
    [(second, unread)] = await inbox.push_many(
        redis, [Delivery(uid, _payload(n=2, v=5, fv=4), "asset.updated:a1")], settings
    )
    assert unread == 1
    entries, _ = await inbox.page(redis, uid, before=None, limit=10, unread_only=False)
    assert len(entries) == 1
    assert entries[0].id == second
    assert entries[0].payload["n"] == 3
    assert entries[0].payload["fv"] == 3
    assert entries[0].payload["v"] == 5


async def test_read_entry_is_never_merged():
    redis, uid = get_redis(), uuid4()
    settings = get_settings()
    [(first, _)] = await inbox.push_many(
        redis, [Delivery(uid, _payload(v=1), "asset.updated:a1")], settings
    )
    await inbox.mark_read(redis, uid, [first])
    await inbox.push_many(redis, [Delivery(uid, _payload(v=2), "asset.updated:a1")], settings)
    entries, _ = await inbox.page(redis, uid, before=None, limit=10, unread_only=False)
    assert [e.read for e in entries] == [False, True]


async def test_cap_trims_log_and_unread_set_together(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "notifications_inbox_max", 3)
    redis, uid = get_redis(), uuid4()
    for i in range(5):
        await inbox.push_many(redis, [Delivery(uid, {"c": "asset.created", "t": str(i)})], settings)
    entries, _ = await inbox.page(redis, uid, before=None, limit=10, unread_only=False)
    assert [e.payload["t"] for e in entries] == ["4", "3", "2"]
    assert await inbox.unread_count(redis, uid) == 3


async def test_mark_unread_delete_clear_and_unread_filter():
    redis, uid = get_redis(), uuid4()
    settings = get_settings()
    results = await inbox.push_many(
        redis, [Delivery(uid, {"c": "asset.created", "t": str(i)}) for i in range(3)], settings
    )
    ids = [r[0] for r in results]
    assert await inbox.mark_read(redis, uid, ids[:2]) == 1
    unread, _ = await inbox.page(redis, uid, before=None, limit=10, unread_only=True)
    assert [e.id for e in unread] == [ids[2]]
    restored, count = await inbox.mark_unread(redis, uid, [ids[0], "999-0"])
    assert restored == [ids[0]] and count == 2
    assert await inbox.delete(redis, uid, ids[0]) == 1
    assert await inbox.delete(redis, uid, ids[0]) is None
    await inbox.clear(redis, uid)
    assert await inbox.unread_count(redis, uid) == 0


async def test_since_replays_missed_entries_or_asks_for_reset():
    redis, uid = get_redis(), uuid4()
    settings = get_settings()
    results = await inbox.push_many(
        redis, [Delivery(uid, {"c": "asset.created", "t": str(i)}) for i in range(3)], settings
    )
    missed = await inbox.since(redis, uid, results[0][0])
    assert missed is not None
    assert [e.payload["t"] for e in missed] == ["1", "2"]
    assert await inbox.since(redis, uid, results[0][0], limit=1) is None


@pytest.mark.parametrize("value", ["1-0", "1727520000000-12"])
def test_entry_id_guard_accepts_ids(value):
    assert inbox.is_entry_id(value)


@pytest.mark.parametrize("value", ["-", "+", "(1-0", "1", "abc-1", ""])
def test_entry_id_guard_rejects_range_syntax(value):
    assert not inbox.is_entry_id(value)


async def test_live_hub_routes_only_subscribed_users_and_flags_overflow():
    redis = get_redis()
    hub = LiveHub(redis)
    alice, bob = uuid4(), uuid4()
    queue = await hub.subscribe(alice)
    await asyncio.sleep(0.05)
    await inbox.publish(redis, bob, "sync", {"unread": 9})
    await inbox.publish(redis, alice, "sync", {"unread": 1})
    message = await asyncio.wait_for(queue.get(), timeout=3)
    assert message["d"] == {"unread": 1}
    for _ in range(80):
        hub._dispatch(inbox.live_channel(alice), '{"e":"sync","id":"","d":{}}')
    assert queue.get_nowait() is OVERFLOW
    await hub.unsubscribe(alice, queue)
    assert hub._queues == {}
    # The connection stays; a new stream of the same user still gets events.
    again = await hub.subscribe(alice)
    await asyncio.sleep(0.05)
    await inbox.publish(redis, alice, "sync", {"unread": 2})
    assert (await asyncio.wait_for(again.get(), timeout=3))["d"] == {"unread": 2}
    await hub.unsubscribe(alice, again)
    if hub._reader is not None:
        hub._reader.cancel()
