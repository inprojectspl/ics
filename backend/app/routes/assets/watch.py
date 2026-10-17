"""Watching one asset (ADR-0023): registered on `crud_router`, like pins.
A watch is the caller's preference, so viewer access is enough."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.db import get_session
from app.services.notifications import watches

from .crud import router


class AssetWatchIn(BaseModel):
    level: watches.AssetLevel


@router.get("/{asset_id}/watch")
async def get_asset_watch(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    asset, _ = await permissions.get_asset_with_role(
        session, user=user, min_role="viewer", asset_id=asset_id
    )
    return await watches.asset_state(session, user.id, asset)


@router.put("/{asset_id}/watch")
async def put_asset_watch(
    asset_id: UUID,
    body: AssetWatchIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    asset, _ = await permissions.get_asset_with_role(
        session, user=user, min_role="viewer", asset_id=asset_id
    )
    await watches.set_asset(session, user.id, asset.id, body.level)
    await session.commit()
    return await watches.asset_state(session, user.id, asset)


@router.delete("/{asset_id}/watch")
async def delete_asset_watch(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    asset, _ = await permissions.get_asset_with_role(
        session, user=user, min_role="viewer", asset_id=asset_id
    )
    await watches.clear_asset(session, user.id, asset.id)
    await session.commit()
    return await watches.asset_state(session, user.id, asset)
