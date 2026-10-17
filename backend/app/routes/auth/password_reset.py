"""Password reset: request (email) + confirm (token + new password)."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, email_templates, passwords, ratelimit, tokens
from app.config import Settings, get_settings
from app.db import get_session
from app.email_outbox import queue_email
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import User
from app.redis_client import get_redis
from app.services.account_lock import locked_by_admin
from app.util import ip_hash as compute_ip_hash

from ._models import PasswordResetConfirmIn, PasswordResetRequestIn
from ._router import _validate_password_or_400, _verify_token_or_400, router


@router.post("/password-reset/request", status_code=status.HTTP_200_OK)
async def password_reset_request(
    body: PasswordResetRequestIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> dict:
    """Returns 200 regardless of whether the email exists (anti-enumeration).
    A rate-limit hit returns 429 with Retry-After: the limit does not depend
    on whether the account exists, so it does not enable enumeration, and an
    operator or legitimate client can see it was throttled."""
    email = body.email.lower()
    redis = get_redis()
    ip_h = compute_ip_hash(request)
    await ratelimit.enforce(
        redis,
        ratelimit.PASSWORD_RESET_REQUEST,
        ip_h,
        "too many password reset requests, try again later",
    )

    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is not None and user.password_hash is not None:
        token = tokens.issue("reset", str(user.id))
        link = f"{settings.base_url}/reset-confirm?token={token}"
        subj, txt, html = email_templates.password_reset(
            reset_url=link,
            locale=resolve_locale(user.locale, accept_language=accept_language),
        )
        await queue_email(
            session,
            to_email=email,
            subject=subj,
            body=txt,
            body_html=html,
            purpose="reset",
        )
        await audit.record(
            session,
            actor=email,
            action="password_reset_requested",
            target=f"user:{user.id}",
            ip_hash=ip_h,
        )
        await session.commit()
    return {"ok": True}


@router.post("/password-reset/confirm", status_code=status.HTTP_200_OK)
async def password_reset_confirm(
    body: PasswordResetConfirmIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    user_id = _verify_token_or_400("reset", body.token)
    _validate_password_or_400(body.new_password)

    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "token_invalid", "invalid token")
    user.password_hash = await asyncio.to_thread(passwords.hash_password, body.new_password)
    # A new password ends a failed-attempt lockout, not a lock an administrator set.
    if not await locked_by_admin(session, user):
        user.locked_until = None
    await audit.record(
        session, actor=user, action="password_reset_confirmed", target=f"user:{user.id}"
    )
    await session.commit()
    return {"ok": True}
