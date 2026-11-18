"""Asset lifecycle: archive, trash (undelete, purge, listing) and tags
(ADR-0029). The web app uses these endpoints too."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.jobs.queue import enqueue
from app.json_response import ORJSONResponse
from app.models import Asset, User
from app.services import asset_lifecycle
from app.services.asset_discovery import discover_assets

from ._models import TagsUpdate
from ._router import router

# One request purges at most this many entries; the rest wait for the next.
_EMPTY_TRASH_MAX = 500


async def _set_archived(
    asset_id: UUID, user: User, session: AsyncSession, request: Request, archived: bool
) -> ORJSONResponse:
    asset = await permissions.get_managed_asset(session, user, asset_id)
    changed = await asset_lifecycle.set_archived(session, user, asset, archived, request=request)
    await session.commit()
    return ORJSONResponse(
        {
            "id": str(asset.id),
            "slug": asset.slug,
            "archived_at": asset.archived_at.isoformat() if asset.archived_at else None,
            "noop": not changed,
        }
    )


@router.post("/{asset_id}/archive")
async def archive_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> ORJSONResponse:
    """Archive: lists and search leave the asset out unless asked for; it
    still opens by link, share and slug. Idempotent."""
    return await _set_archived(asset_id, user, session, request, True)


@router.delete("/{asset_id}/archive")
async def unarchive_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> ORJSONResponse:
    """Bring an asset back from the archive. Idempotent."""
    return await _set_archived(asset_id, user, session, request, False)


@router.post("/{asset_id}/undelete")
async def undelete_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> ORJSONResponse:
    """Take an asset out of the trash. Shares and links are not restored.
    An asset that is not in the trash answers `noop`, to its managers only."""
    asset = await permissions.get_managed_asset(session, user, asset_id, in_trash=None)
    noop = asset.deleted_at is None
    if not noop:
        await asset_lifecycle.restore(session, user, asset, request=request)
        await session.commit()
        await enqueue("rebuild_outline", str(asset.id), _job_id=f"outline:{asset.id}")
    return ORJSONResponse(
        {"id": str(asset.id), "slug": asset.slug, "deleted_at": None, "noop": noop}
    )


class EmptyTrash(BaseModel):
    project_id: UUID | None = None
    # An administrator empties the whole organisation's trash only when
    # asking for it; anyone else always empties their own.
    everyone: bool = False


# Static paths before `/{asset_id}/...`, which would take `trash` for an id.
@router.post("/trash/purge")
async def empty_trash(
    body: EmptyTrash,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> ORJSONResponse:
    """Purge everything in the caller's trash, or in one project's trash.
    `remaining` counts what is left for another call."""
    purged, remaining = await asset_lifecycle.purge_batch(
        session,
        settings,
        asset_lifecycle.trash_filter(user, body.project_id, everyone=body.everyone),
        limit=_EMPTY_TRASH_MAX,
        actor=user,
        request=request,
    )
    await session.commit()
    return ORJSONResponse({"purged": purged, "remaining": remaining})


@router.post("/{asset_id}/purge")
async def purge_asset(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> ORJSONResponse:
    """Delete an asset from the trash for good, with all its versions and
    files. Only an asset already in the trash; there is no way back."""
    asset = await permissions.get_managed_asset(session, user, asset_id, in_trash=True)
    slug = asset.slug
    await asset_lifecycle.purge_batch(
        session,
        settings,
        and_(Asset.id == asset_id, Asset.deleted_at.is_not(None)),
        limit=1,
        actor=user,
        request=request,
    )
    await session.commit()
    return ORJSONResponse({"id": str(asset_id), "slug": slug, "purged": True})


# The trash rows of an agent: the web list's, without what an agent does not
# pick an entry by.
_TRASH_ITEM_KEYS = (
    "id",
    "slug",
    "title",
    "kind",
    "project_id",
    "size_bytes",
    "archived_at",
    "deleted_at",
    "deleted_by",
    "purge_at",
)


@router.get("/trash")
async def list_trash(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    project_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ORJSONResponse:
    """The caller's trash, most recently deleted first: their own assets and
    those of projects they own. `project_id` narrows it to one project. The
    same query as the web app's `scope=state:trash`."""
    page = await discover_assets(
        session,
        user,
        scope="state:trash",
        filters=[f"project:{project_id}"] if project_id else (),
        limit=limit,
        offset=offset,
    )
    items = [{k: row.get(k) for k in _TRASH_ITEM_KEYS} for row in page["items"]]
    total = page["total"]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return ORJSONResponse({"items": items, "total": total, "next_offset": next_offset})


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
