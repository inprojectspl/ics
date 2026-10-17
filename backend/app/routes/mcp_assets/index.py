"""Token-efficient listings: `/index` (cursor-paginated) + `/by-slug/{slug}/meta`."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.json_response import ORJSONResponse
from app.models import Asset, AssetPin, AssetShare, ProjectMember
from app.services import doc_types, ocr
from app.services.asset_projection import (
    AssetMetadataRow,
    detail_fields,
    load_metadata,
    metadata_fields,
)
from app.services.document_search import search_filter
from app.services.freshness import FilterableFreshness
from app.services.project_shares import in_project_filter
from app.util import now as utc_now

from ._models import AssetIndexItem, AssetIndexPage, AssetMetaItem
from ._router import router
from ._shared import (
    _DEFAULT_LIMIT,
    _MAX_LIMIT,
    _build_role_case,
    _decode_cursor,
    _encode_cursor,
    metadata_filters,
)


def _index_item(
    asset: Asset,
    *,
    pinned: bool,
    role: str,
    metadata: AssetMetadataRow | None,
    now: datetime,
    preview: bool,
    shared_in: bool = False,
) -> AssetIndexItem:
    return AssetIndexItem.model_validate(
        {
            "id": asset.id,
            "slug": asset.slug,
            "title": asset.title,
            "kind": asset.kind,
            "size_bytes": asset.size_bytes,
            "version": asset.version,
            "updated_at": asset.updated_at,
            "content_updated_at": asset.content_updated_at,
            "content_updated_by": asset.content_updated_by,
            "pinned": pinned,
            "owner_id": asset.owner_id,
            "project_id": asset.project_id,
            "tags": list(asset.tags or []),
            "has_versions": asset.version > 1,
            "access_role": role,
            "shared_in": shared_in,
            **metadata_fields(asset, metadata, now, preview=preview),
        }
    )


@router.get("/index", response_model=AssetIndexPage)
async def assets_index(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=_MAX_LIMIT)] = _DEFAULT_LIMIT,
    kind: Annotated[list[str] | None, Query()] = None,
    project_id: UUID | None = None,
    pinned: bool | None = None,
    shared_with_me: bool | None = None,
    owned: bool | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
    doc_type: Annotated[list[str] | None, Query()] = None,
    freshness: Annotated[list[FilterableFreshness] | None, Query()] = None,
    maintainer: UUID | None = None,
    updated_since: Annotated[
        datetime | None,
        Query(description="Assets whose content (a new version) changed at or after this time."),
    ] = None,
    touched_since: Annotated[
        datetime | None,
        Query(description="Assets whose row changed at or after this time, metadata included."),
    ] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> Response:
    # `shared_with_me`/`owned=False` narrow to assets reached through someone
    # else; admins ignore them.
    if user.acts_as_admin or (not shared_with_me and owned is not False):
        base_filter = permissions.visible_assets_filter(user)
    else:
        base_filter = and_(
            Asset.deleted_at.is_(None),
            permissions.shared_with_user_filter(user),
        )

    stmt = (
        select(
            Asset,
            _build_role_case(user).label("role"),
            AssetPin.pinned_at.label("pinned_at"),
        )
        .outerjoin(
            ProjectMember,
            and_(
                ProjectMember.project_id == Asset.project_id,
                ProjectMember.user_id == user.id,
                ProjectMember.accepted_at.is_not(None),
            ),
        )
        .outerjoin(
            AssetShare,
            and_(
                AssetShare.asset_id == Asset.id,
                AssetShare.user_id == user.id,
            ),
        )
        # Pins are per user: the join is scoped to the caller, and the filter and
        # the `pinned` flag come from asset_pins (shared ON clause: AssetPin.for_user).
        .outerjoin(AssetPin, AssetPin.for_user(user.id))
        .where(base_filter)
    )

    if doc_type:
        await doc_types.check_filter_keys(session, doc_type)
    if kind:
        stmt = stmt.where(Asset.kind.in_(kind))
    if project_id is not None:
        # Assets assigned to the project (ADR-0017) are listed with their home.
        stmt = stmt.where(in_project_filter(project_id))
    if pinned is True:
        stmt = stmt.where(AssetPin.pinned_at.is_not(None))
    elif pinned is False:
        stmt = stmt.where(AssetPin.pinned_at.is_(None))
    now = utc_now()
    stmt = stmt.where(
        *metadata_filters(
            doc_type=doc_type,
            freshness=freshness,
            tag=tag,
            maintainer=maintainer,
            now=now,
            viewer=user,
        )
    )
    if updated_since is not None:
        stmt = stmt.where(Asset.content_updated_at >= updated_since)
    if touched_since is not None:
        stmt = stmt.where(Asset.updated_at >= touched_since)
    if q is not None:
        stmt = stmt.where(search_filter(q))

    if cursor:
        dec = _decode_cursor(cursor)
        if dec is None:
            raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_cursor", "invalid_cursor")
        cur_updated, cur_id = dec
        stmt = stmt.where(
            or_(
                Asset.updated_at < cur_updated,
                and_(Asset.updated_at == cur_updated, Asset.id < cur_id),
            )
        )

    stmt = stmt.order_by(Asset.updated_at.desc(), Asset.id.desc()).limit(limit + 1)

    rows = (await session.execute(stmt)).unique().all()
    items_rows = rows[:limit]
    has_more = len(rows) > limit
    metadata = await load_metadata(session, [asset for asset, _, _ in items_rows], user)
    items = [
        _index_item(
            asset,
            pinned=pin_at is not None,
            role=role or "viewer",
            metadata=metadata.get(asset.id),
            now=now,
            preview=True,
            shared_in=project_id is not None and asset.project_id != project_id,
        )
        for asset, role, pin_at in items_rows
    ]
    last_asset: Asset | None = items_rows[-1][0] if items_rows else None
    next_cursor = (
        _encode_cursor(last_asset.updated_at, last_asset.id) if has_more and last_asset else None
    )
    page = AssetIndexPage(items=items, next_cursor=next_cursor)

    accept = request.headers.get("accept", "")
    if "application/x-ndjson" in accept:

        async def _ndjson():
            for item in page.items:
                yield (item.model_dump_json() + "\n").encode()
            if page.next_cursor:
                yield (json.dumps({"next_cursor": page.next_cursor}) + "\n").encode()

        return StreamingResponse(_ndjson(), media_type="application/x-ndjson")
    return ORJSONResponse(page.model_dump(mode="json"))


@router.get("/by-slug/{slug}/meta")
async def asset_meta(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> Response:
    asset, role = await permissions.get_asset_with_role(
        session, user=user, min_role="viewer", slug=slug
    )
    # The ETag is per user (it includes the pin); shared caches are covered by
    # the `Vary: Cookie` SessionMiddleware adds to every session response.
    pin = await session.get(AssetPin, (user.id, asset.id))
    metadata = (await load_metadata(session, [asset], user)).get(asset.id)
    row = _index_item(
        asset,
        pinned=pin is not None,
        role=role,
        metadata=metadata,
        now=utc_now(),
        preview=False,
    )
    settings = get_settings()
    body = AssetMetaItem.model_validate({**row.model_dump(), **detail_fields(asset)})
    # Metadata edits move `updated_at` without a new version, and freshness
    # and flags change with the clock and with related documents, so they are
    # part of the ETag too.
    successor = f"{body.superseded_by.id}.{body.latest}" if body.superseded_by else "-"
    etag = (
        f'W/"v{asset.version}-u{asset.updated_at.timestamp():.6f}'
        f"-{body.freshness}-{successor}-{'.'.join(body.flags)}-p{1 if pin else 0}"
        f'-o{await ocr.state_tag(session, asset, asset.version, settings)}"'
    )
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304)
    # Only a 200 pays for the OCR block (it may read the document's meta).
    body.ocr = await ocr.ocr_state(session, asset, asset.version, settings)
    return ORJSONResponse(body.model_dump(mode="json"), headers={"ETag": etag})
