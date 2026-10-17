"""Admin-driven email flows: invite, reinvite, password-reset trigger."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, email_templates, tokens
from app.auth import AdminUser
from app.config import Settings, get_settings
from app.db import get_session
from app.email_outbox import queue_email
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import User
from app.routes.auth.invite import create_invited_user

from ._models import InviteIn
from ._router import router
from ._shared import _user_row


@router.post("", status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteIn,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> dict:
    """Thin alias for /api/auth/invite: keeps the admin panel calls
    grouped under /api/admin/users for discoverability."""
    email = body.email.lower()
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT, "user_exists", "a user with this email already exists"
        )

    user = await create_invited_user(
        session,
        settings,
        admin=admin,
        email=email,
        role=body.role,
        display_name=body.display_name,
        accept_language=accept_language,
        audit_extra={"via": "admin_panel"},
    )
    await session.commit()
    await session.refresh(user)
    return _user_row(user)


@router.post("/{user_id}/password-reset", status_code=status.HTTP_200_OK)
async def admin_password_reset(
    user_id: UUID,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> dict:
    """Send the user a reset link. The admin doesn't see or set the new
    password; they trigger the standard reset flow on the user's
    behalf. Keeps the audit chain clean."""
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "user not found")
    if user.auth_method != "password":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "password_account_required",
            "password reset is only possible for accounts with auth_method=password",
        )
    token = tokens.issue("reset", str(user.id))
    link = f"{settings.base_url}/reset-confirm?token={token}"
    subj, txt, html = email_templates.password_reset(
        reset_url=link,
        requested_by_admin=True,
        admin_email=admin.email,
        locale=resolve_locale(user.locale, admin.locale, accept_language=accept_language),
    )
    await queue_email(
        session,
        to_email=user.email,
        subject=subj,
        body=txt,
        body_html=html,
        purpose="reset",
    )
    await audit.record(
        session,
        actor=admin,
        action="user_password_reset_by_admin",
        target=f"user:{user.id}",
    )
    await session.commit()
    return {"sent_to": user.email}


@router.post("/{user_id}/reinvite", status_code=status.HTTP_200_OK)
async def reinvite(
    user_id: UUID,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> dict:
    """For accounts that never completed setup (email_verified_at IS NULL):
    re-issue a fresh invite token + email. The original invite token
    stays valid until expiry: both work, until one is consumed."""
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "user not found")
    if user.email_verified_at is not None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "account_already_active",
            "the account is already active; reinvite is only for unverified accounts",
        )
    token = tokens.issue("invite", str(user.id))
    link = f"{settings.base_url}/setup?token={token}"
    subj, txt, html = email_templates.reinvite(
        invited_by_email=admin.email,
        setup_url=link,
        locale=resolve_locale(user.locale, admin.locale, accept_language=accept_language),
    )
    await queue_email(
        session,
        to_email=user.email,
        subject=subj,
        body=txt,
        body_html=html,
        purpose="invite",
    )
    await audit.record(
        session,
        actor=admin,
        action="user_reinvited",
        target=f"user:{user.id}",
    )
    await session.commit()
    return {"sent_to": user.email}
