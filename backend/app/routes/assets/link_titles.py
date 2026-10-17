"""Titles for `[[ics:<slug>]]` links in rendered Markdown (ADR-0006).

The cached HTML carries only slugs; titles are resolved per viewer here, and
invisible slugs are left out exactly like unknown ones.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.db import get_session
from app.models import Asset

from .view import router

# One page of Markdown rarely links more documents than this.
MAX_LINK_SLUGS = 100


@router.get("/link-titles")
async def link_titles(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    slug: Annotated[list[str] | None, Query(max_length=MAX_LINK_SLUGS)] = None,
) -> dict[str, str]:
    """`{slug: title}` for the visible assets among `slug`."""
    wanted = {s for s in slug or [] if s}
    if not wanted:
        return {}
    rows = await session.execute(
        select(Asset.slug, Asset.title).where(
            Asset.slug.in_(wanted),
            Asset.title.is_not(None),
            permissions.visible_assets_filter(user),
        )
    )
    return {s: title for s, title in rows.all() if title}
