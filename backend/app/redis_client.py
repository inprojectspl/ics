from functools import lru_cache

from redis.asyncio import Redis

from app.config import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url, decode_responses=True)


@lru_cache
def get_cache_redis() -> Redis:
    """The render cache's Redis: `render_cache_redis_url`, else the main one."""
    settings = get_settings()
    if not settings.render_cache_redis_url or settings.render_cache_redis_url == settings.redis_url:
        return get_redis()
    return Redis.from_url(settings.render_cache_redis_url, decode_responses=True)
