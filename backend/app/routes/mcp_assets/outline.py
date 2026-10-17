"""Outline endpoints: GET cached + POST rebuild."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Annotated, Any
from uuid import UUID

import orjson
from fastapi import Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.db import get_session
from app.jobs.queue import enqueue
from app.json_response import ORJSONResponse
from app.models import Asset, User
from app.outline_parser import with_end_lines
from app.services.asset_projection import freshness_block
from app.services.graph_compact import Shape
from app.services.relation_views import outgoing_compact, outgoing_edges

from ._router import router


async def _graph_block(
    session: AsyncSession, user: User, asset: Asset, *, edges: bool, shape: Shape
) -> dict[str, Any]:
    """Summary, freshness and successor for every reader; outgoing edges
    (with anchors into their targets) only with graph access (ADR-0016), in
    the compact shape as `nodes` plus `edges` triples (section 10)."""
    block = await freshness_block(session, asset, user)
    if edges and await permissions.has_graph_access(session, user, asset):
        if shape == "compact":
            block |= await outgoing_compact(session, user, asset)
        else:
            block["edges"] = await outgoing_edges(session, user, asset)
    return block


def _body(outline: dict[str, Any] | None, graph: dict[str, Any]) -> dict[str, Any]:
    return {**with_end_lines(outline or {}), **graph}


@router.get("/by-slug/{slug}/outline")
async def asset_outline(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    wait: bool = False,
    timeout: Annotated[int, Query(ge=1, le=10)] = 5,
    edges: bool = True,
    shape: Shape = "full",
) -> Response:
    asset, _ = await permissions.get_asset_with_role(
        session, user=user, min_role="viewer", slug=slug
    )
    graph = await _graph_block(session, user, asset, edges=edges, shape=shape)
    # Freshness and edges change without a new outline, so they are in the ETag.
    digest = hashlib.sha256(orjson.dumps(graph)).hexdigest()[:16]
    etag = f'W/"outline-v{asset.outline_version or 0}-{digest}"'
    if request.headers.get("if-none-match") == etag and asset.outline_status == "fresh":
        return Response(status_code=304)

    fresh = (
        asset.outline_status == "fresh"
        and asset.outline_version == asset.version
        and asset.outline_json is not None
    )
    if fresh:
        return ORJSONResponse(_body(asset.outline_json, graph), headers={"ETag": etag})

    if asset.outline_status == "failed":
        return ORJSONResponse(
            {"status": "failed", "error": asset.outline_error},
            status_code=500,
        )

    # Enqueue if not already in flight and we have nothing cached.
    if asset.outline_json is None:
        await enqueue("rebuild_outline", str(asset.id), _job_id=f"outline:{asset.id}")
        if wait:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            while loop.time() < deadline:
                await asyncio.sleep(0.25)
                await session.refresh(asset)
                if asset.outline_status == "fresh" and asset.outline_version == asset.version:
                    return ORJSONResponse(
                        _body(asset.outline_json, graph),
                        headers={"ETag": f'W/"outline-v{asset.outline_version}-{digest}"'},
                    )
        return ORJSONResponse(
            {"status": "building", "retry_after": 2},
            status_code=202,
            headers={"Retry-After": "2"},
        )

    # Stale: return what we have with X-Outline-Stale and schedule a rebuild
    # now instead of waiting for the sweeper (the job id deduplicates).
    if asset.outline_status == "stale":
        await enqueue("rebuild_outline", str(asset.id), _job_id=f"outline:{asset.id}")
    return ORJSONResponse(
        _body(asset.outline_json, graph),
        headers={
            "ETag": etag,
            "X-Outline-Stale": "true",
            "X-Outline-Version": str(asset.outline_version or 0),
            "X-Asset-Version": str(asset.version),
        },
    )


@router.post("/{asset_id}/outline/rebuild", status_code=202)
async def rebuild_outline_now(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ORJSONResponse:
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    asset.outline_status = "stale"
    asset.outline_error = None
    await session.commit()
    await enqueue("rebuild_outline", str(asset.id), _job_id=f"outline:{asset.id}")
    return ORJSONResponse({"status": "scheduled", "asset_id": str(asset.id)}, status_code=202)
