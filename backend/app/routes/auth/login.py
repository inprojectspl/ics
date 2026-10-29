"""Login + logout endpoints."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Annotated, NoReturn

from fastapi import Depends, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, passwords, ratelimit, session_store
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import AuthAttempt, User
from app.redis_client import get_redis
from app.util import ip_hash as compute_ip_hash
from app.util import now as utc_now

from ._models import LoginIn
from ._router import _AUTH_FAIL, _dummy_hash, _record_attempt, router


async def _login_fail(
    session: AsyncSession,
    email: str,
    ip_hash: str,
    reason: str = "bad_credentials",
) -> NoReturn:
    await _record_attempt(session, email, ip_hash, succeeded=False)
    await audit.record(
        session,
        actor=email,
        action="login_failed",
        payload={"reason": reason},
        ip_hash=ip_hash,
    )
    await session.commit()
    raise ApiError(status.HTTP_401_UNAUTHORIZED, "invalid_credentials", _AUTH_FAIL)


@router.post("/login", status_code=status.HTTP_200_OK)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    email = body.email.lower()
    ip_hash = compute_ip_hash(request)
    redis = get_redis()
    now = utc_now()

    if not await ratelimit.check_and_incr(redis, ratelimit.LOGIN, f"{ip_hash}:{email}"):
        await audit.record(
            session,
            actor=email,
            action="login_rate_limited",
            ip_hash=ip_hash,
        )
        await session.commit()
        # 429 + Retry-After instead of a silent 401, so a client can tell a
        # throttled login from bad credentials.
        retry_after = await ratelimit.retry_after_seconds(
            redis, ratelimit.LOGIN, f"{ip_hash}:{email}"
        )
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate_limited",
            "too many login attempts, try again later",
            headers={"Retry-After": str(retry_after)},
        )

    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()

    # Constant-time path: verify against dummy hash so missing-user response
    # time matches existing-user response time.
    if user is None or user.password_hash is None:
        # Argon2 (~150-300 ms CPU) must run in the threadpool, otherwise it blocks the event loop.
        await asyncio.to_thread(passwords.verify_password, body.password, _dummy_hash())
        await _login_fail(session, email, ip_hash, reason="no_password_user")

    if user.is_locked:
        await _login_fail(session, email, ip_hash, reason="account_locked")

    if not await asyncio.to_thread(passwords.verify_password, body.password, user.password_hash):
        await _record_attempt(session, email, ip_hash, succeeded=False)
        recent_failures = (
            await session.scalar(
                select(func.count())
                .select_from(AuthAttempt)
                .where(
                    AuthAttempt.email == email,
                    AuthAttempt.succeeded.is_(False),
                    AuthAttempt.timestamp > now - timedelta(hours=1),
                )
            )
            or 0
        )
        locked = recent_failures >= settings.lockout_threshold
        if locked:
            user.locked_until = now + timedelta(minutes=settings.lockout_minutes)
        await audit.record(
            session,
            actor=email,
            action="account_locked" if locked else "login_failed",
            target=f"user:{user.id}",
            payload={"recent_failures": recent_failures},
            ip_hash=ip_hash,
        )
        await session.commit()
        if locked:
            # Lockout must also revoke active sessions, otherwise an
            # attacker who already holds a cookie carries on despite
            # the lock. See session_store.revoke_all_user_sessions.
            revoked_n = await session_store.revoke_all_user_sessions(redis, str(user.id))
            await audit.record(
                session,
                actor=email,
                action="sessions_revoked_on_lockout",
                target=f"user:{user.id}",
                payload={"sids_revoked": revoked_n},
                ip_hash=ip_hash,
            )
            await session.commit()
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "invalid_credentials", _AUTH_FAIL)

    if user.email_verified_at is None:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, "account_unverified", "the account is not verified yet"
        )

    if passwords.needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(passwords.hash_password, body.password)

    user.last_login_at = now
    user.locked_until = None
    await _record_attempt(session, email, ip_hash, succeeded=True)
    await audit.record(
        session,
        actor=user,
        action="login_ok",
        target=f"user:{user.id}",
        ip_hash=ip_hash,
    )
    await session.commit()

    await ratelimit.reset(redis, ratelimit.LOGIN, f"{ip_hash}:{email}")
    # Every login gets a fresh sid, so a single session can be revoked
    # without affecting the user's other devices.
    await session_store.bind_session(request, redis, str(user.id))
    return {"ok": True}


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    uid = request.session.get(session_store.SESSION_KEY)
    await session_store.revoke_request_session(request, get_redis())
    if uid:
        await audit.record(session, actor=f"user_id:{uid}", action="logout")
        await session.commit()
    return {"ok": True}
