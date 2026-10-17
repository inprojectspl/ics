"""Arq connection pool and enqueue helper, used by request handlers after a
commit. Outline rebuilds pass `_job_id="outline:{asset_id}"` so overlapping
writes coalesce into one rebuild.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import Settings, get_settings


def _redis_settings(settings: Settings) -> RedisSettings:
    url = settings.arq_redis_url or settings.redis_url
    parsed = urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/") or 0),
        password=parsed.password,
    )


_pool: ArqRedis | None = None


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(_redis_settings(get_settings()))
    return _pool


async def enqueue(function: str, *args: Any, **kwargs: Any):
    pool = await get_pool()
    return await pool.enqueue_job(function, *args, **kwargs)


@lru_cache
def worker_redis_settings() -> RedisSettings:
    return _redis_settings(get_settings())
