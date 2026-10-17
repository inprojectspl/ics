"""Asset reads: tree, download, render, graph, source, search and listing.

`by-slug/{slug}/*` reads are viewer level (`get_viewable_asset_by_slug`):
owner, any project member and AssetShare recipients.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.collections_io import (
    list_md_paths,
    normalize_collection_path,
    read_text_at_version,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.graph import build_graph
from app.models import Asset
from app.routes._version_param import (
    VersionParam,
    entry_path_or_404,
    resolve_version_or_404,
    version_echo,
)
from app.routes.assets._helpers import (
    _load_asset_html,
    _stream_source,
    assert_bundle_renderable_for_visitors,
    render_collection_file,
    serve_bundle_file,
)
from app.services import documents
from app.services.asset_discovery import discover_assets
from app.services.asset_filters import AssetScope
from app.services.asset_sort import AssetSortKey, SortOrder
from app.services.document_search import SearchMatch

router = APIRouter(prefix="/api/assets", tags=["assets"])


def _gate_bundle_for_read_only(role: permissions.EffectiveRole, asset: Asset) -> None:
    """Visitor gate (410 for critical content) for read-only roles; editors
    skip it to inspect a bundle before review."""
    if permissions.is_read_only(role):
        assert_bundle_renderable_for_visitors(asset)


@router.get("/by-slug/{slug}/tree")
async def collection_tree(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    asset, _ = await permissions.get_viewable_asset_by_slug(session, slug, user)
    if asset.kind != "md_collection":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "collection_only", "tree only for md_collection"
        )
    return {
        "slug": asset.slug,
        "entry_path": asset.entry_path,
        "paths": await list_md_paths(asset, settings),
    }


@router.get("/by-slug/{slug}/download")
async def asset_download(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    """Download of the source files, viewer level like the share-link
    download; a critical bundle is gated as for visitors."""
    asset, role = await permissions.get_viewable_asset_by_slug(session, slug, user)
    _gate_bundle_for_read_only(role, asset)
    return await _stream_source(asset, settings)


@router.get("/by-slug/{slug}/file")
async def collection_file(
    slug: str,
    path: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    version: VersionParam = None,
) -> dict:
    asset, _ = await permissions.get_viewable_asset_by_slug(session, slug, user)
    return await render_collection_file(asset, path, version, settings)


@router.get("/by-slug/{slug}/static/{path:path}")
async def asset_static(
    slug: str,
    path: str,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Sandboxed preview for legacy direct links; normal rendering goes
    through the isolated viewer via `/html-grant`."""
    asset, role = await permissions.get_viewable_asset_by_slug(session, slug, user)
    _gate_bundle_for_read_only(role, asset)
    return await serve_bundle_file(
        asset, path, settings, session=session, request=request, app_origin=True
    )


@router.get("/by-slug/{slug}/render", response_class=HTMLResponse)
async def render_asset(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """Raw sanitized HTML for legacy/embedding use. Frontend prefers /doc."""
    asset, _ = await permissions.get_viewable_asset_by_slug(session, slug, user)
    return HTMLResponse(await _load_asset_html(asset, settings))


@router.get("/by-slug/{slug}/graph")
async def get_graph(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Wikilink graph of an md_collection: .md files and `[[wikilinks]]`."""
    asset, _ = await permissions.get_viewable_asset_by_slug(session, slug, user)
    if asset.kind != "md_collection":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "collection_only",
            "graph available only for vaults (md_collection)",
        )
    return await build_graph(asset, settings)


@router.get("/by-slug/{slug}/source")
async def get_source(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    path: Annotated[str | None, Query()] = None,
    version: VersionParam = None,
) -> dict:
    """Raw Markdown source for inline edit. Viewer level on purpose: it
    carries the same information as `/download`. md_collection needs `path`."""
    asset, _ = await permissions.get_viewable_asset_by_slug(session, slug, user)
    if asset.kind == "html_bundle":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "html_bundle_not_editable",
            "HTML bundles have no editable source",
        )
    if documents.is_document(asset.kind):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            documents.document_type(asset.kind).not_editable_code,
            "documents have no editable source; upload a new version",
        )
    v = resolve_version_or_404(asset, version)
    if asset.kind == "md_collection":
        if not path:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, "path_required", "md_collection requires ?path="
            )
        rel = normalize_collection_path(path)
    else:
        # An archived md_single may have had a different file name.
        rel = await entry_path_or_404(asset, v, settings)
    try:
        content = await read_text_at_version(asset, v, rel, settings)
    except FileNotFoundError:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "file_not_found",
            f"file {rel} does not exist in version v{v}",
        ) from None
    return {"path": rel, "content": content, **version_echo(asset, v)}


# ---------- Search + list (static paths, registered before crud) ----------


@router.get("/search")
async def search_my_assets(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: Annotated[AssetSortKey | None, Query()] = None,
    order: Annotated[SortOrder | None, Query()] = None,
    match: SearchMatch = "all",
) -> list[dict]:
    """Authorized document search for pickers. Use `/api/assets?q=...` to page.

    All words by default, quoted phrases, accent-insensitive prefixes.
    Searches title, slug, summary, tags and extracted current content.
    Relevance order unless an explicit sort is supplied.
    """
    result = await discover_assets(
        session, user, q=q, match=match, limit=limit, sort=sort, order=order
    )
    return result["items"]


@router.get("")
async def list_my_assets(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    sort: Annotated[AssetSortKey | None, Query()] = None,
    order: Annotated[SortOrder | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    match: SearchMatch = "all",
    scope: AssetScope = "all",
    f: Annotated[list[str] | None, Query(max_length=50)] = None,
    facets: bool = False,
) -> dict:
    """Visible documents; search, scope and filters apply before pagination.

    Default sort: relevance with `q`, most recently changed without it.
    `facets` adds counts over matching documents, independent of the page.
    Repeated `f=kind:value` values are OR within a kind, AND across kinds.
    """
    result = await discover_assets(
        session,
        user,
        q=q,
        match=match,
        limit=page_size,
        offset=(page - 1) * page_size,
        sort=sort,
        order=order,
        scope=scope,
        filters=f or (),
        facets=facets,
    )
    return {**result, "page": page, "page_size": page_size}
