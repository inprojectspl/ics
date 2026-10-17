"""Server-side revocation for Starlette's stateless signed session cookies.

A copied cookie stays valid until max_age, so each session carries a `sid` checked
against Redis; `user_sids:{user_id}` lets a lockout revoke them all. Redis (not
Postgres like Bearer `jti`s) because a sid only matters until its cookie expires.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable
from typing import cast

from fastapi import Request
from redis.asyncio import Redis

# Defined here rather than in auth.py to avoid an import cycle.
SESSION_KEY = "user_id"
SESSION_SID_KEY = "sid"

# Starlette's default cookie max_age = 2 weeks (1_209_600s). A revoked sid
# is kept for as long, so the Redis key expires when the cookie would.
TTL_SECONDS = 14 * 24 * 3600
# Bounds the per-user SET; a typical user has about 5 live sessions.
_MAX_TRACKED_PER_USER = 50


def new_sid() -> str:
    """43-character URL-safe random ID (256 bits of entropy)."""
    return secrets.token_urlsafe(32)


def _revoked_key(sid: str) -> str:
    return f"revoked_sid:{sid}"


def _user_index_key(user_id: str) -> str:
    return f"user_sids:{user_id}"


# The casts in this module: redis-py annotates set commands with one signature
# for the sync and async clients (`Awaitable[T] | T`), which mypy cannot await.
async def track_user_session(redis: Redis, user_id: str, sid: str) -> None:
    """Add `sid` to `user_id`'s session index, TTL'd like the cookie. Over the cap a
    random sid is dropped (SETs are unordered), which only risks long-expired ones."""
    key = _user_index_key(user_id)
    pipe = redis.pipeline()
    pipe.sadd(key, sid)
    pipe.expire(key, TTL_SECONDS)
    pipe.scard(key)
    _, _, card = await pipe.execute()
    if card > _MAX_TRACKED_PER_USER:
        await cast(Awaitable[str | None], redis.spop(key))


async def is_revoked(redis: Redis, sid: str) -> bool:
    return bool(await redis.exists(_revoked_key(sid)))


async def revoke_sid(
    redis: Redis,
    sid: str,
    *,
    user_id: str | None = None,
) -> None:
    """Write `sid` to the revoked store. An optional `user_id` also removes
    it from the user_sids index (clean state after logout)."""
    await redis.setex(_revoked_key(sid), TTL_SECONDS, "1")
    if user_id is not None:
        await cast(Awaitable[int], redis.srem(_user_index_key(user_id), sid))


async def revoke_all_user_sessions(redis: Redis, user_id: str) -> int:
    """Revoke all sessions of `user_id`; run on account lockout and password
    reset. Returns the number of revoked sids (for the audit log)."""
    key = _user_index_key(user_id)
    sids = await cast(Awaitable[set[str]], redis.smembers(key))
    if not sids:
        return 0
    pipe = redis.pipeline()
    for sid in sids:
        pipe.setex(_revoked_key(sid), TTL_SECONDS, "1")
    pipe.delete(key)
    await pipe.execute()
    return len(sids)


# Request-level helpers shared by the login, Google callback and OAuth
# authorize handlers.


async def bind_session(request: Request, redis: Redis, user_id: str) -> str:
    """Issue a fresh sid after a successful login, track it and write it to the cookie."""
    sid = new_sid()
    await track_user_session(redis, user_id, sid)
    request.session[SESSION_KEY] = user_id
    request.session[SESSION_SID_KEY] = sid
    return sid


async def revoke_request_session(request: Request, redis: Redis) -> str | None:
    """Revoke the request's sid and clear the cookie; returns the sid, if any.
    Idempotent: an anonymous request is a no-op."""
    uid = request.session.get(SESSION_KEY)
    sid = request.session.get(SESSION_SID_KEY)
    request.session.clear()
    if sid:
        await revoke_sid(redis, sid, user_id=uid)
    return sid
