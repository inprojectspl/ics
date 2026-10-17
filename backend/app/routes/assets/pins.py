"""Per-user pins ("favourites"): pin/unpin an asset.

Registered on `crud_router`. A pin is a preference of the caller, not an
asset mutation, so viewer access is enough.
"""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy import CursorResult
from sqlalchemy import delete as _delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions
from app.auth import CurrentUser
from app.db import get_session
from app.models import AssetPin
from app.util import now as utc_now

from .crud import router


@router.post("/{asset_id}/pin", status_code=status.HTTP_200_OK)
async def pin_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Idempotent pin; re-pinning bumps the timestamp. A pin is a per-user
    preference, not an asset mutation, so viewer level is enough."""
    asset, _ = await permissions.get_asset_with_role(
        session,
        user=user,
        min_role="viewer",
        asset_id=asset_id,
    )
    now = utc_now()
    # Atomic upsert instead of check-then-insert: two concurrent POSTs from
    # the same user (double-click) cannot end in an IntegrityError on the
    # composite PK; ON CONFLICT just bumps the timestamp.
    await session.execute(
        pg_insert(AssetPin)
        .values(user_id=user.id, asset_id=asset.id, pinned_at=now)
        .on_conflict_do_update(
            index_elements=[AssetPin.user_id, AssetPin.asset_id],
            set_={"pinned_at": now},
        )
    )
    await audit.record(
        session,
        actor=user,
        action="asset_pinned",
        target=f"asset:{asset.id}",
    )
    await session.commit()
    return {"id": str(asset.id), "pinned_at": now.isoformat()}


@router.delete("/{asset_id}/pin", status_code=status.HTTP_200_OK)
async def unpin_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    asset, _ = await permissions.get_asset_with_role(
        session,
        user=user,
        min_role="viewer",
        asset_id=asset_id,
    )
    # Atomic DELETE (instead of get-then-delete): rowcount tells whether the
    # pin existed, so concurrent unpins do not race on ORM state.
    result = await session.execute(
        _delete(AssetPin).where(
            AssetPin.user_id == user.id,
            AssetPin.asset_id == asset.id,
        )
    )
    if cast(CursorResult, result).rowcount == 0:
        # Idempotent on the empty side too: silent success matches the
        # "double-click the pin icon" UX without surfacing 404.
        return {"id": str(asset.id), "pinned_at": None}
    await audit.record(
        session,
        actor=user,
        action="asset_unpinned",
        target=f"asset:{asset.id}",
    )
    await session.commit()
    return {"id": str(asset.id), "pinned_at": None}
