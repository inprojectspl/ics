"""Admin-driven invite + token-based account setup."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, email_templates, passwords, tokens
from app.auth import AdminUser, domain_of
from app.config import Settings, get_settings
from app.db import get_session
from app.email_outbox import queue_email
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import User
from app.util import now as utc_now

from ._models import InviteIn, SetupFromTokenIn
from ._router import _validate_password_or_400, _verify_token_or_400, router


async def create_invited_user(
    session: AsyncSession,
    settings: Settings,
    *,
    admin: User,
    email: str,
    role: str,
    display_name: str | None,
    accept_language: str | None,
    audit_extra: dict | None = None,
) -> User:
    """Add an unverified invited account, queue its invite email and audit
    it; setup turns it into a password account. Shared by /api/auth/invite
    and the admin panel; the caller commits."""
    # External email can't have the 'user' role, downgrade to 'external'.
    if role == "user" and domain_of(email) not in settings.allowed_domain_list:
        role = "external"

    user = User(
        email=email,
        display_name=display_name or email.split("@")[0],
        role=role,
        auth_method="invite",
        email_verified_at=None,
    )
    session.add(user)
    await session.flush()

    token = tokens.issue("invite", str(user.id))
    link = f"{settings.base_url}/setup?token={token}"
    subj, txt, html = email_templates.invite(
        invited_by_email=admin.email,
        setup_url=link,
        locale=resolve_locale(admin.locale, accept_language=accept_language),
    )
    await queue_email(
        session,
        to_email=email,
        subject=subj,
        body=txt,
        body_html=html,
        purpose="invite",
    )
    await audit.record(
        session,
        actor=admin,
        action="user_invited",
        target=f"user:{user.id}",
        payload={"invited_email": email, "role": role, **(audit_extra or {})},
    )
    return user


@router.post("/invite", status_code=status.HTTP_201_CREATED)
async def invite(
    body: InviteIn,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> dict:
    email = body.email.lower()
    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise ApiError(status.HTTP_409_CONFLICT, "user_exists", "user already exists")

    user = await create_invited_user(
        session,
        settings,
        admin=admin,
        email=email,
        role=body.role,
        display_name=body.display_name,
        accept_language=accept_language,
    )
    await session.commit()
    return {"id": str(user.id), "email": user.email, "role": user.role}


@router.post("/setup", status_code=status.HTTP_200_OK)
async def setup_from_token(
    body: SetupFromTokenIn,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    user_id = _verify_token_or_400("invite", body.token)
    _validate_password_or_400(body.password)

    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "token_invalid", "invalid token")

    user.password_hash = await asyncio.to_thread(passwords.hash_password, body.password)
    # A share or project invite creates the account as `invite`; with a password set it is
    # a password account, which the admin password reset requires.
    if user.auth_method == "invite":
        user.auth_method = "password"
    user.email_verified_at = utc_now()
    if body.display_name:
        user.display_name = body.display_name
    await audit.record(
        session, actor=user, action="account_setup_completed", target=f"user:{user.id}"
    )
    await session.commit()
    return {"ok": True}
