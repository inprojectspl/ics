"""Caller-info endpoints: /me, /me/quota, /config."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.models import User

from ._models import MePatchIn
from ._router import router


def _me_payload(user: User, settings: Settings) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "role": user.role,
        "auth_method": user.auth_method,
        "email_verified": user.email_verified_at is not None,
        "locale": user.locale,
        "dev_stub_sso": settings.dev_stub_sso,
    }


@router.get("/me")
async def me(user: CurrentUser, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    return _me_payload(user, settings)


@router.patch("/me")
async def patch_me(
    body: MePatchIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Profile preferences of the caller. `locale: null` goes back to the
    browser's language."""
    user.locale = body.locale
    await session.commit()
    return _me_payload(user, settings)


@router.get("/me/quota")
async def me_quota(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Storage usage for the sidebar indicator. Computed on-the-fly,
    not denormalized: current-version size_bytes summed across the
    user's live assets only (deleted + historical versions don't count)."""
    from app import quota

    used = await quota.used_bytes(session, user.id)
    return {
        "used_bytes": used,
        "quota_bytes": user.storage_quota_bytes,
    }


@router.get("/config")
async def auth_config(settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """Public; the front-end uses this to decide which login methods to render."""
    return {
        "google_oidc_enabled": bool(settings.google_oidc_client_id),
        "self_register_enabled": settings.allow_self_register,
        "dev_stub_sso": settings.dev_stub_sso,
        "sync_image": settings.sync_image,
    }
