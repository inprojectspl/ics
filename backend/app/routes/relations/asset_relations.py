"""Relations of one asset: list, add, update, remove (ADR-0016)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.models import Asset, AssetRelation, User
from app.services import relation_extraction
from app.services import relations as relations_svc
from app.services.graph_compact import Shape
from app.services.relation_views import (
    Direction,
    compact_relation,
    edge_fields,
    get_relation,
    list_for_asset,
    outgoing_compact,
)

from ._router import router
from ._shared import transport_of


class AddRelationIn(BaseModel):
    # A plain string: an unknown type is `relation_type_invalid`, not a 422.
    relation_type: str
    target_id: UUID | None = None
    target_slug: str | None = None
    source_path: str | None = Field(default=None, max_length=1024)
    target_path: str | None = Field(default=None, max_length=1024)
    target_anchor: str | None = Field(default=None, max_length=512)
    note: str | None = Field(default=None, max_length=500)


class PatchRelationIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)
    refresh_target_version: bool = False


async def _edge_out(session: AsyncSession, user: User, edge: AssetRelation, shape: Shape) -> dict:
    """The written edge: the full shape the web client reads, or with
    `shape=compact` the agent shape of `GET /relations/{id}`."""
    if shape == "compact":
        return await compact_relation(session, user, edge)
    target = await session.get(Asset, edge.target_asset_id)
    return edge_fields(edge, target.version if target is not None else None)


@router.get("/assets/by-slug/{slug}/relations")
async def get_relations(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    types: Annotated[list[str] | None, Query()] = None,
    direction: Direction = "both",
    shape: Shape = "full",
) -> dict:
    """`shape=compact` is the agent format (ADR-0016, section 10)."""
    asset = await permissions.get_graph_asset(session, user, slug=slug)
    return await list_for_asset(session, user, asset, types=types, direction=direction, shape=shape)


@router.post("/assets/{asset_id}/relations", status_code=status.HTTP_201_CREATED)
async def add_relation(
    asset_id: UUID,
    body: AddRelationIn,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    shape: Shape = "full",
) -> dict:
    edge = await relations_svc.add_relation(
        session,
        actor=user,
        source_id=asset_id,
        relation_type=body.relation_type,
        target_id=body.target_id,
        target_slug=body.target_slug,
        source_path=body.source_path,
        target_path=body.target_path,
        target_anchor=body.target_anchor,
        note=body.note,
        **transport_of(request),
    )
    await session.commit()
    return await _edge_out(session, user, edge, shape)


@router.post("/assets/{asset_id}/relations/rescan")
async def rescan_relations(
    asset_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Extract relations from the current content again (ADR-0016, section
    4). Answers with the outgoing relations in the compact shape."""
    asset, counts = await relation_extraction.rescan(
        session, asset_id, user, settings, **transport_of(request)
    )
    await session.commit()
    return {"asset": asset.slug, **counts, **await outgoing_compact(session, user, asset)}


@router.get("/relations/{relation_id}")
async def get_relation_by_id(
    relation_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """One edge in the compact agent shape (ADR-0016, section 10)."""
    return await get_relation(session, user, relation_id)


@router.patch("/relations/{relation_id}")
async def patch_relation(
    relation_id: UUID,
    body: PatchRelationIn,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    shape: Shape = "full",
) -> dict:
    edge = await relations_svc.update_relation(
        session,
        actor=user,
        relation_id=relation_id,
        note=body.note,
        set_note="note" in body.model_fields_set,
        refresh_target_version=body.refresh_target_version,
        **transport_of(request),
    )
    await session.commit()
    return await _edge_out(session, user, edge, shape)


@router.delete("/relations/{relation_id}")
async def delete_relation(
    relation_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    await relations_svc.remove_relation(
        session, actor=user, relation_id=relation_id, **transport_of(request)
    )
    await session.commit()
    return {"deleted": True}
