"""Public-by-token auth endpoints: info, password challenge, magic claim and
the share-link entry of a micro-application."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, tokens
from app.config import Settings, get_settings
from app.constants import MICRO_APPLICATION
from app.db import get_session
from app.errors import ApiError
from app.models import MicroAppEnvironment
from app.routes.micro_applications import callback_redirect, require_enabled
from app.services.micro_applications import access, runtime
from app.services.micro_applications.common import ENVIRONMENT
from app.services.micro_applications.hosts import app_url
from app.util import ip_hash

from ._models import MagicClaimIn, PasswordChallengeIn
from ._router import router
from ._shared import (
    _assert_share_view,
    _direct_role,
    _identity,
    _increment_view_count,
    _mark_verified,
    _mode_allows,
    _parse_magic_payload,
    _resolve_share,
    _verify_share_password,
)


@router.get("/api/share/{token}/info")
async def share_info(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    share, asset = await _resolve_share(token, session)
    base = {
        "mode": share.mode,
        "title": asset.title,
        "expires_at": share.expires_at.isoformat() if share.expires_at else None,
        "kind": asset.kind,
    }
    if asset.kind == MICRO_APPLICATION and settings.microapps_enabled:
        # The visit starts on the app's own origin (browser-bound start).
        base["app_launch_url"] = await _app_launch_url(session, settings, asset, token)

    # A role on the asset lifts every mode challenge: we don't ask the owner
    # for the password to their own document. Only a role holder gets `slug`;
    # the UI uses it to mount the full reader at `/s/<token>`.
    role = await _direct_role(request, asset, session, settings)
    if role is not None:
        return {
            **base,
            "requires_password": False,
            "requires_login": False,
            "requires_magic_link": False,
            "has_access": True,
            "my_role": role,
            "slug": asset.slug,
        }

    # Challenges derive from the same answer as access, or a logged-in
    # magic-link recipient would still see the "open the message" wall.
    allows = await _mode_allows(request, share, session, settings)
    return {
        **base,
        "requires_password": share.mode == "password" and not allows,
        "requires_login": share.mode == "org_sso"
        and not allows
        and not request.session.get("user_id"),
        "requires_magic_link": share.mode == "magic_email" and not allows,
        "has_access": allows,
        "my_role": None,
        "slug": None,
    }


@router.post("/api/share/{token}/auth", status_code=status.HTTP_200_OK)
async def share_password_auth(
    token: str,
    body: PasswordChallengeIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    share, _ = await _resolve_share(token, session)
    if share.mode != "password" or share.password_hash is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "share_not_password", "this link does not use a password"
        )

    await _verify_share_password(share, body.password, request, session)
    _mark_verified(request, share.id)
    await audit.record(
        session,
        actor=None,
        action="share_password_ok",
        target=f"share:{share.id}",
        ip_hash=ip_hash(request),
    )
    await session.commit()
    return {"ok": True}


@router.post("/api/share/{token}/magic-claim", status_code=status.HTTP_200_OK)
async def share_magic_claim(
    token: str,
    body: MagicClaimIn,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Verify a magic-link token. The signed payload binds the share to one
    specific email, so a leaked URL can only unlock that single recipient's
    seat. Marks the share as verified in this browser session on success."""
    share, _asset = await _resolve_share(token, session)
    if share.mode != "magic_email":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "share_not_magic_email",
            "this link does not use magic-email",
        )

    try:
        payload = tokens.verify("magic_link", body.m)
    except tokens.TokenExpired:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "link_expired", "link expired") from None
    except tokens.TokenInvalid:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "link_invalid", "invalid link") from None

    try:
        sid, email = _parse_magic_payload(payload)
    except (ValueError, IndexError):
        raise ApiError(status.HTTP_400_BAD_REQUEST, "link_invalid", "invalid link") from None

    if sid != share.id:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "link_invalid", "the link does not match this document"
        )
    if not share.allowed_emails or email not in share.allowed_emails:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "email_not_allowed",
            "this address is not on the recipient list",
        )

    _mark_verified(request, share.id)
    await audit.record(
        session,
        actor=email,
        action="share_magic_claimed",
        target=f"share:{share.id}",
        ip_hash=ip_hash(request),
    )
    await session.commit()
    return {"ok": True, "email": email}


async def _app_launch_url(
    session: AsyncSession, settings: Settings, asset, token: str
) -> str | None:
    env = await session.scalar(
        select(MicroAppEnvironment).where(
            MicroAppEnvironment.asset_id == asset.id,
            MicroAppEnvironment.environment == ENVIRONMENT,
        )
    )
    return f"{app_url(settings, env)}__ics/share?token={token}" if env else None


@router.get("/api/share/{token}/launch")
async def share_launch(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    host: Annotated[str, Query(max_length=200)],
    state: Annotated[str, Query(max_length=128)],
) -> RedirectResponse:
    """Share-link entry of a micro-application. A member who may use the app
    enters as themselves, uncounted; anyone else passes the link's own gate
    (password, sign-in, e-mail) and gets a one-time code bound to the link.
    Each such launch counts against `max_views`."""
    require_enabled(settings)
    share_page = RedirectResponse(f"/s/{quote(token, safe='')}", status_code=302)
    try:
        share, asset = await _resolve_share(token, session)
    except ApiError:
        # Unknown, revoked, expired or spent: the share page explains it.
        return share_page
    if asset.kind != MICRO_APPLICATION:
        return share_page
    user = await _identity(request, session, settings)
    if user is not None and (await access.rights(session, user, asset)).use:
        code = await runtime.issue_launch_code(session, settings, user, host, state)
        return callback_redirect(settings, host, code)
    try:
        await _assert_share_view(request, share, asset, session, settings)
    except ApiError as e:
        if e.code == "share_login_required" and user is None:
            return RedirectResponse(
                f"/#login?next={quote(f'/s/{token}', safe='')}", status_code=302
            )
        if e.code in ("share_login_required", "share_password_required", "share_access_denied"):
            # The share page asks for the password or the e-mail link, or
            # tells a signed-in visitor this link is not for them.
            return share_page
        raise
    code = await runtime.issue_share_launch_code(session, settings, share, host, state)
    await _increment_view_count(session, share.id)
    await session.commit()
    return callback_redirect(settings, host, code)
