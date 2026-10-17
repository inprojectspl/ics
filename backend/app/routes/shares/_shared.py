"""Shared helpers: share resolution, mode-aware view authorization, magic payload."""

from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, passwords, permissions, ratelimit
from app.auth import get_optional_user
from app.config import Settings
from app.errors import ApiError
from app.models import Asset, ShareLink, User
from app.redis_client import get_redis
from app.services import link_resolution
from app.services.sharing import build_share_url
from app.util import ip_hash

from ._models import ShareOut
from ._router import SESSION_VERIFIED_KEY


def _magic_payload(share_id: UUID, email: str) -> str:
    return f"{share_id}|{email.lower()}"


def _parse_magic_payload(payload: str) -> tuple[UUID, str]:
    sid, _, email = payload.partition("|")
    return UUID(sid), email


def _to_out(share: ShareLink, settings: Settings) -> ShareOut:
    return ShareOut(
        id=str(share.id),
        token=share.token,
        mode=share.mode,
        url=build_share_url(settings, share.token),
        expires_at=share.expires_at,
        max_views=share.max_views,
        view_count=share.view_count,
        revoked_at=share.revoked_at,
        created_at=share.created_at,
        allowed_emails=list(share.allowed_emails) if share.allowed_emails else None,
        requires_password=bool(share.password_hash),
    )


#: 410 (code, message) per `link_resolution.link_lifecycle` reason.
_GONE_ERROR: dict[str, tuple[str, str]] = {
    "revoked": ("share_revoked", "link has been revoked"),
    "expired": ("share_expired", "link has expired"),
    "spent": ("share_spent", "link open limit reached"),
}


async def _resolve_share(token: str, session: AsyncSession) -> tuple[ShareLink, Asset]:
    """Returns (share, asset) or raises 404/410."""
    result = await session.execute(
        select(ShareLink, Asset)
        .join(Asset, Asset.id == ShareLink.asset_id)
        .where(ShareLink.token == token)
    )
    row = result.one_or_none()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "share_not_found", "link does not exist")
    share, asset = row
    if asset.deleted_at is not None:
        raise ApiError(status.HTTP_410_GONE, "share_revoked", "link has been revoked")
    fault = link_resolution.link_lifecycle(share)
    if fault is not None:
        code, message = _GONE_ERROR[fault]
        raise ApiError(status.HTTP_410_GONE, code, message)
    return share, asset


def _is_verified(request: Request, share_id: UUID) -> bool:
    verified = request.session.get(SESSION_VERIFIED_KEY) or []
    return str(share_id) in verified


def _mark_verified(request: Request, share_id: UUID) -> None:
    verified = list(request.session.get(SESSION_VERIFIED_KEY) or [])
    if str(share_id) not in verified:
        verified.append(str(share_id))
        request.session[SESSION_VERIFIED_KEY] = verified


_IDENTITY_STATE = "_ics_share_identity"


async def _identity(request: Request, session: AsyncSession, settings: Settings) -> User | None:
    """Who is calling, cached per request (a Redis round-trip plus a SELECT)."""
    if not hasattr(request.state, _IDENTITY_STATE):
        setattr(
            request.state,
            _IDENTITY_STATE,
            await get_optional_user(request, session, settings),
        )
    return getattr(request.state, _IDENTITY_STATE)


async def _direct_role(
    request: Request,
    asset: Asset,
    session: AsyncSession,
    settings: Settings,
) -> permissions.EffectiveRole | None:
    """Role the caller already holds on the asset, ignoring the link, so a
    team member is never challenged for a document they can open anyway."""
    user = await _identity(request, session, settings)
    if user is None:
        return None
    return await permissions.effective_role(session, user, asset)


async def _mode_allows(
    request: Request,
    share: ShareLink,
    session: AsyncSession,
    settings: Settings,
) -> bool:
    """The link's own gate, regardless of the caller's role on the asset:
    the session flag from a challenge, else `link_resolution.mode_admits`."""
    # Public: skip the identity lookup on the hottest anonymous path.
    if share.mode == "public":
        return True
    if share.mode in ("password", "magic_email") and _is_verified(request, share.id):
        return True
    user = await _identity(request, session, settings)
    return link_resolution.mode_admits(share, user, settings.allowed_domain_list)


async def _assert_share_view(
    request: Request,
    share: ShareLink,
    asset: Asset,
    session: AsyncSession,
    settings: Settings,
    *,
    need_role: bool = False,
) -> permissions.EffectiveRole | None:
    """Authorize a visit; with `need_role`, return the caller's role so a
    team member is not charged against the view budget.

    The cheap link gate runs first, the role lookup is the fallback.
    """
    if await _mode_allows(request, share, session, settings):
        return await _direct_role(request, asset, session, settings) if need_role else None
    role = await _direct_role(request, asset, session, settings)
    if role is not None:
        return role
    if share.mode == "password":
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "share_password_required", "password required")
    if share.mode == "org_sso":
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "share_login_required", "login required")
    raise ApiError(status.HTTP_403_FORBIDDEN, "share_access_denied", "access denied")


def _can_view_as_user(share: ShareLink, user: User, settings: Settings) -> bool:
    """Mode-aware access for an authenticated user, without the browser
    session flag."""
    return link_resolution.mode_admits(share, user, settings.allowed_domain_list)


async def _verify_share_password(
    share: ShareLink,
    password: str,
    request: Request,
    session: AsyncSession,
    *,
    actor: User | None = None,
) -> None:
    """Password challenge shared by `POST /auth` and `POST /resolve`, with one
    rate-limit bucket per (IP, share) for both. A failure is audited and
    committed before the 401, which would otherwise roll it back."""
    redis = get_redis()
    scope = f"{ip_hash(request)}:{share.id}"
    if not await ratelimit.check_and_incr(redis, ratelimit.SHARE_PASSWORD, scope):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "share_password_invalid", "invalid password")

    ok = share.password_hash is not None and await asyncio.to_thread(
        passwords.verify_password, password, share.password_hash
    )
    if not ok:
        await audit.record(
            session,
            actor=actor,
            action="share_password_failed",
            target=f"share:{share.id}",
            ip_hash=ip_hash(request),
        )
        await session.commit()
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "share_password_invalid", "invalid password")

    await ratelimit.reset(redis, ratelimit.SHARE_PASSWORD, scope)


async def _increment_view_count(session: AsyncSession, share_id: UUID) -> None:
    """Atomic SQL-side increment (not read-modify-write on the ORM object, so
    two concurrent visitors can't lose a count). The caller commits."""
    await session.execute(
        update(ShareLink)
        .where(ShareLink.id == share_id)
        .values(view_count=ShareLink.view_count + 1)
    )
