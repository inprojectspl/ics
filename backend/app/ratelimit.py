from dataclasses import dataclass

from fastapi import status
from redis.asyncio import Redis

from app.errors import ApiError


@dataclass(frozen=True)
class RateLimit:
    """Fixed window (INCR + TTL): good enough for login-style flows."""

    name: str
    limit: int
    window_seconds: int


LOGIN = RateLimit("login", limit=5, window_seconds=15 * 60)
PASSWORD_RESET_REQUEST = RateLimit("pwreset", limit=5, window_seconds=60 * 60)
SHARE_PASSWORD = RateLimit("share_pw", limit=5, window_seconds=15 * 60)

# Link resolver (`/by-slug/{slug}/entry`): the only asset endpoint that
# answers anonymous callers, so it is also the cheapest slug-enumeration
# surface. 30/min per IP leaves a human pasting links untouched.
LINK_ENTRY = RateLimit("link_entry", limit=30, window_seconds=60)

# Binding sync is unauthenticated by design (signed payloads), so cap how
# often one IP can make the server parse and verify a push.
BINDING_SYNC = RateLimit("binding_sync", limit=30, window_seconds=60)

# OAuth-side buckets, per IP, protecting the authorization-server surface.
OAUTH_DCR = RateLimit("oauth_dcr", limit=5, window_seconds=60 * 60)
OAUTH_TOKEN = RateLimit("oauth_token", limit=60, window_seconds=60)
OAUTH_AUTHORIZE = RateLimit("oauth_authorize", limit=30, window_seconds=60)

# MCP endpoints, per user: catches a runaway agent loop, not a human.
MCP_API = RateLimit("mcp_api", limit=600, window_seconds=60)

# Personal access tokens (ADR-0020): the same budget as MCP traffic, in a
# bucket of its own so a local script does not eat the agent's quota.
PAT_API = RateLimit("pat_api", limit=600, window_seconds=60)

# Agent context pack (ADR-0019): an agent loop has no reason to ask more often.
CONTEXT_PACK = RateLimit("context_pack", limit=120, window_seconds=60)

# Notification settings (ADR-0023): the Chat test posts to Google, and the
# e-mail opt-out endpoint takes no login.
NOTIFY_CHAT_TEST = RateLimit("notify_chat_test", limit=5, window_seconds=60)
NOTIFY_UNSUBSCRIBE = RateLimit("notify_unsub", limit=30, window_seconds=60)


async def check_and_incr(redis: Redis, rl: RateLimit, scope: str) -> bool:
    """Return True if allowed; denied calls count too, to discourage hammering."""
    key = f"rl:{rl.name}:{scope}"
    # One pipeline, so a crash between the commands cannot leave a key without a TTL.
    pipe = redis.pipeline()
    pipe.incr(key)
    pipe.expire(key, rl.window_seconds, nx=True)
    count, _ = await pipe.execute()
    return int(count) <= rl.limit


async def retry_after_seconds(redis: Redis, rl: RateLimit, scope: str) -> int:
    """Seconds until the current window resets, for `Retry-After`; the full window
    when the key or its TTL is missing."""
    key = f"rl:{rl.name}:{scope}"
    ttl = await redis.ttl(key)
    if ttl < 0:
        return rl.window_seconds
    return max(ttl, 1)


async def enforce(redis: Redis, rl: RateLimit, scope: str, detail: str = "rate_limited") -> None:
    """Count the request and raise 429 `rate_limited` with `Retry-After`
    when the bucket is over its limit."""
    if await check_and_incr(redis, rl, scope):
        return
    retry = await retry_after_seconds(redis, rl, scope)
    raise ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "rate_limited",
        detail,
        headers={"Retry-After": str(retry)},
    )


async def reset(redis: Redis, rl: RateLimit, scope: str) -> None:
    await redis.delete(f"rl:{rl.name}:{scope}")
