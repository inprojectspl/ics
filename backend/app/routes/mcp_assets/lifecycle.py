"""Asset lifecycle: undelete + tag updates."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions
from app.auth import CurrentUser
from app.db import get_session
from app.errors import ApiError
from app.jobs.queue import enqueue
from app.json_response import ORJSONResponse
from app.models import Asset

from ._models import TagsUpdate
from ._router import router


@router.post("/{asset_id}/undelete")
async def undelete_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> ORJSONResponse:
    asset = await session.get(Asset, asset_id)
    if asset is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    # Ownership first: even the no-op answer names the slug.
    if not user.acts_as_admin and asset.owner_id != user.id:
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    if asset.deleted_at is None:
        return ORJSONResponse(
            {"id": str(asset.id), "slug": asset.slug, "deleted_at": None, "noop": True}
        )
    asset.deleted_at = None
    await audit.record_from_request(
        session, request, actor=user, action="asset_undeleted", target=f"asset:{asset.id}"
    )
    await session.commit()
    # Outline cache may be stale after a long absence: re-enqueue.
    asset.outline_status = "stale"
    await session.commit()
    await enqueue("rebuild_outline", str(asset.id), _job_id=f"outline:{asset.id}")
    return ORJSONResponse(
        {"id": str(asset.id), "slug": asset.slug, "deleted_at": None, "noop": False}
    )


@router.put("/{asset_id}/tags")
async def set_tags(
    asset_id: UUID,
    body: TagsUpdate,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> ORJSONResponse:
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    asset.tags = body.tags
    await audit.record_from_request(
        session,
        request,
        actor=user,
        action="asset_tags_set",
        target=f"asset:{asset.id}",
        payload={"tags": body.tags},
    )
    await session.commit()
    return ORJSONResponse({"id": str(asset.id), "tags": asset.tags})
