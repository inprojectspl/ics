"""Public-by-token auth endpoints: info, password challenge, magic claim."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, tokens
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.util import ip_hash

from ._models import MagicClaimIn, PasswordChallengeIn
from ._router import router
from ._shared import (
    _direct_role,
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
    }

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
