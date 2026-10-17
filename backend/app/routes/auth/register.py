"""Self-registration + email verification."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import email_templates, passwords, tokens
from app.config import Settings, get_settings
from app.db import get_session
from app.email_outbox import queue_email
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import User
from app.util import now as utc_now

from ._models import RegisterIn
from ._router import _role_from_domain, _validate_password_or_400, _verify_token_or_400, router


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterIn,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> dict:
    if not settings.allow_self_register:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, "self_register_disabled", "self-registration is disabled"
        )
    _validate_password_or_400(body.password)

    email = body.email.lower()
    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        # Generic to avoid enumeration; still 201 to keep timing consistent.
        return {"ok": True}

    password_hash = await asyncio.to_thread(passwords.hash_password, body.password)
    user = User(
        email=email,
        display_name=body.display_name or email.split("@")[0],
        role=_role_from_domain(email, settings),
        auth_method="password",
        password_hash=password_hash,
        email_verified_at=None,
    )
    session.add(user)
    await session.flush()

    token = tokens.issue("verify", str(user.id))
    link = f"{settings.base_url}/verify?token={token}"
    subj, txt, html = email_templates.verify_email(
        verify_url=link, locale=resolve_locale(accept_language=accept_language)
    )
    await queue_email(
        session,
        to_email=email,
        subject=subj,
        body=txt,
        body_html=html,
        purpose="verify",
    )
    await session.commit()
    return {"ok": True}


@router.post("/verify", status_code=status.HTTP_200_OK)
async def verify_email(token: str, session: Annotated[AsyncSession, Depends(get_session)]) -> dict:
    user_id = _verify_token_or_400("verify", token)
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "token_invalid", "invalid token")
    if user.email_verified_at is None:
        user.email_verified_at = utc_now()
        await session.commit()
    return {"ok": True}
