"""One `AssetSummary` row by slug, for the viewer's management widgets.

Editor+ only: the row carries metadata (share modes, binding state) that
read-only collaborators must not see.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.db import get_session
from app.models import AssetPin
from app.services.asset_listing import build_asset_summaries

from .view import router


@router.get("/by-slug/{slug}/summary")
async def get_asset_summary(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """One AssetSummary row, from the caller's perspective."""
    asset, _ = await permissions.get_asset_with_role(
        session,
        user=user,
        min_role="editor",
        slug=slug,
    )
    pinned_at = (
        await session.execute(
            select(AssetPin.pinned_at).where(
                AssetPin.asset_id == asset.id,
                AssetPin.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    pin_at_by_asset: dict[UUID, datetime | None] = {asset.id: pinned_at}
    rows = await build_asset_summaries(
        session,
        user,
        [asset],
        pin_at_by_asset=pin_at_by_asset,
    )
    return rows[0]
