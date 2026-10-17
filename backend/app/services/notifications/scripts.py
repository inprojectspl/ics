"""Lua scripts run by SHA (ADR-0023, section 5). `register_script` in a pipeline
costs a `SCRIPT EXISTS` round trip per execute; here the source is loaded only
on `NOSCRIPT` and the whole batch retried, which is safe because a missing
script fails every call of the batch alike.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import Pipeline
from redis.exceptions import NoScriptError


class LuaScript:
    def __init__(self, source: str) -> None:
        self.source = source
        self.sha = hashlib.sha1(source.encode()).hexdigest()

    def queue(self, pipe: Pipeline, keys: Sequence[str], args: Sequence[Any]) -> None:
        pipe.evalsha(self.sha, len(keys), *keys, *args)

    async def batch(self, redis: Redis, build: Callable[[Pipeline], None]) -> list[Any]:
        """Run the calls `build` queues on a pipeline, loading the script once
        when needed."""
        for attempt in range(2):
            pipe = redis.pipeline(transaction=False)
            build(pipe)
            try:
                return await pipe.execute()
            except NoScriptError:
                if attempt:
                    raise
                await redis.script_load(self.source)
        raise AssertionError("unreachable")

    async def run(self, redis: Redis, keys: Sequence[str], args: Sequence[Any]) -> Any:
        [result] = await self.batch(redis, lambda pipe: self.queue(pipe, keys, args))
        return result
