"""Google OIDC login + callback."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, session_store
from app.auth import domain_of
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import User
from app.oauth import get_oauth
from app.redis_client import get_redis
from app.services.account_lock import locked_by_admin
from app.util import ip_hash as compute_ip_hash
from app.util import now as utc_now

from ._router import router


async def require_google_oidc(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Settings:
    if not settings.google_oidc_client_id:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "google_oidc_disabled",
            "Google OIDC is not configured",
        )
    return settings


# Both locks share `users.locked_until`; the latest of these audit events tells
# who set the current one.


@router.get("/google/login")
async def google_login(
    request: Request,
    settings: Annotated[Settings, Depends(require_google_oidc)],
) -> RedirectResponse:
    redirect_uri = f"{settings.base_url}/api/auth/google/callback"
    return await get_oauth().google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback")
async def google_callback(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(require_google_oidc)],
) -> RedirectResponse:
    ip = compute_ip_hash(request)
    try:
        token = await get_oauth().google.authorize_access_token(request)
    except Exception as e:
        await audit.record(
            session,
            actor="anonymous",
            action="login_failed",
            payload={"reason": "google_oauth_error", "error": str(e)[:200]},
            ip_hash=ip,
        )
        await session.commit()
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "google_rejected", "Google rejected the request"
        ) from e

    info = token.get("userinfo")
    if not info or not info.get("email"):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "google_email_missing", "the Google response has no email"
        )
    email = info["email"].lower()
    # Default False: a missing flag means the IdP didn't confirm verification,
    # so refuse loudly rather than admit an unverified address.
    if not info.get("email_verified", False):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "google_email_unverified",
            "Google has not verified the address",
        )
    if domain_of(email) not in settings.allowed_domain_list:
        await audit.record(
            session,
            actor=email,
            action="login_failed",
            payload={"reason": "domain_not_allowed"},
            ip_hash=ip,
        )
        await session.commit()
        raise ApiError(status.HTTP_403_FORBIDDEN, "domain_not_allowed", "domain not allowed")

    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    now = utc_now()
    if user is None:
        user = User(
            email=email,
            display_name=info.get("name") or email.split("@")[0],
            avatar_url=info.get("picture"),
            role="user",
            auth_method="google_sso",
            email_verified_at=now,
        )
        session.add(user)
        await session.flush()
    else:
        # Account linking: password-user can log in via Google, and vice
        # versa. Refresh display_name/avatar only when locally empty.
        if not user.display_name and info.get("name"):
            user.display_name = info["name"]
        if not user.avatar_url and info.get("picture"):
            user.avatar_url = info["picture"]
        if user.email_verified_at is None:
            user.email_verified_at = now

    # A successful SSO sign-in proves identity, so it lifts a failed-password
    # lockout; an administrator's lock stays until the administrator lifts it.
    if await locked_by_admin(session, user):
        await audit.record(
            session,
            actor=email,
            action="login_failed",
            target=f"user:{user.id}",
            payload={"reason": "account_locked", "via": "google_sso"},
            ip_hash=ip,
        )
        await session.commit()
        raise ApiError(status.HTTP_403_FORBIDDEN, "account_locked", "account locked")

    user.last_login_at = now
    if user.locked_until is not None:
        user.locked_until = None
    await audit.record(
        session,
        actor=user,
        action="login_ok",
        target=f"user:{user.id}",
        payload={"via": "google_sso"},
        ip_hash=ip,
    )
    await session.commit()
    await session_store.bind_session(request, get_redis(), str(user.id))
    return RedirectResponse(url=settings.base_url, status_code=status.HTTP_302_FOUND)
