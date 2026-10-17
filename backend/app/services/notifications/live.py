"""Live event hub of one API process (ADR-0023, section 6). One Redis pub/sub
connection subscribes to `ntf:live:{uid}` only while that user has a stream
open here. A stream whose bounded queue overflows gets `OVERFLOW` and is
closed; the client reconnects and resumes from its last id.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Final
from uuid import UUID

import orjson
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from app.redis_client import get_redis

from .inbox import live_channel

logger = logging.getLogger("ics.notifications.live")

OVERFLOW: Final[object] = object()
_QUEUE_SIZE: Final[int] = 64
_PREFIX: Final[str] = live_channel("")


class LiveHub:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._queues: dict[str, set[asyncio.Queue[Any]]] = {}
        self._pubsub: PubSub | None = None
        self._reader: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def subscribe(self, uid: UUID) -> asyncio.Queue[Any]:
        key = str(uid)
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        async with self._lock:
            if self._pubsub is None:
                self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            if key not in self._queues:
                self._queues[key] = set()
                await self._pubsub.subscribe(live_channel(key))
            self._queues[key].add(queue)
            if self._reader is None or self._reader.done():
                self._reader = asyncio.create_task(self._read(), name="ntf-live-reader")
        return queue

    async def unsubscribe(self, uid: UUID, queue: asyncio.Queue[Any]) -> None:
        key = str(uid)
        async with self._lock:
            queues = self._queues.get(key)
            if queues is None:
                return
            queues.discard(queue)
            if not queues:
                del self._queues[key]
                if self._pubsub is not None:
                    try:
                        await self._pubsub.unsubscribe(live_channel(key))
                    except Exception as e:
                        logger.warning("live unsubscribe failed: %s", type(e).__name__)
            # The connection and the reader stay for the life of the process:
            # on a quiet server the count keeps going 0 -> 1 -> 0, and
            # reconnecting each time would cost a TCP handshake per tab.

    def _dispatch(self, channel: str, raw: str) -> None:
        queues = self._queues.get(channel.removeprefix(_PREFIX))
        if not queues:
            return
        message = orjson.loads(raw)
        for queue in list(queues):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                # A stuck client: drop what it has and tell it to resync.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(OVERFLOW)

    async def _read(self) -> None:
        while True:
            pubsub = self._pubsub
            if pubsub is None:
                return
            try:
                message = await pubsub.get_message(timeout=5.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("live reader error: %s", type(e).__name__)
                await asyncio.sleep(1.0)
                await self._resubscribe()
                continue
            if message and message.get("type") == "message":
                self._dispatch(str(message["channel"]), str(message["data"]))

    async def _resubscribe(self) -> None:
        async with self._lock:
            if self._pubsub is None or not self._queues:
                return
            # The old connection is already broken; closing it is best effort.
            with contextlib.suppress(Exception):
                await self._pubsub.aclose()
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
            try:
                await self._pubsub.subscribe(*(live_channel(k) for k in self._queues))
            except Exception as e:
                logger.warning("live resubscribe failed: %s", type(e).__name__)


_hubs: dict[int, LiveHub] = {}


def get_hub() -> LiveHub:
    """One hub per event loop (tests run each case on a fresh loop)."""
    loop_id = id(asyncio.get_running_loop())
    hub = _hubs.get(loop_id)
    if hub is None:
        _hubs.clear()
        hub = _hubs[loop_id] = LiveHub(get_redis())
    return hub
