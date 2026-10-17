"""Link resolver for `/v/<slug>`, the one asset endpoint an anonymous caller
may use: the SPA asks it how to get in when the viewer fails to load. Rules
are in `services.link_resolution`."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions, ratelimit
from app.auth import OptionalUser
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.redis_client import get_redis
from app.services import link_resolution
from app.services.sharing import build_share_url
from app.util import ip_hash

from .view import router


@router.get("/by-slug/{slug}/entry")
async def resolve_entry(
    slug: str,
    request: Request,
    user: OptionalUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Resolve a pasted `/v/<slug>` into a way in for this caller.

    Every negative outcome is the same 404 and the endpoint is rate limited
    per IP: it is the cheapest enumeration surface for anonymous callers.
    """
    redis = get_redis()
    if not await ratelimit.check_and_incr(redis, ratelimit.LINK_ENTRY, ip_hash(request)):
        raise ApiError(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", "too many attempts")

    asset = await permissions.get_asset_by_slug_or_404(session, slug)

    role = await permissions.effective_role(session, user, asset) if user else None
    if role is not None:
        return {"action": "view", "slug": asset.slug}

    decision = link_resolution.resolve_entry(
        role=None,
        user=user,
        shares=await link_resolution.load_shares(session, asset.id),
        allowed_domains=settings.allowed_domain_list,
    )
    if decision is None or decision.action == "view":
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")

    if decision.action == "login":
        return {"action": "login", "slug": asset.slug}
    assert decision.token is not None
    return {"action": "redirect", "url": build_share_url(settings, decision.token)}
