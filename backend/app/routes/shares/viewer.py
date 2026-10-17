"""Public-by-token content viewer: doc, download, pdf, file, graph, html-grant, static."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.routes._version_param import VersionParam, resolve_version_or_404
from app.services import documents, superseded
from app.services.versions import version_rows

from ._router import router
from ._shared import _assert_share_view, _identity, _increment_view_count, _resolve_share


@router.get("/api/share/{token}/versions")
async def share_versions(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> list[dict]:
    """Version history behind the same gate as `/doc`, in the shape of
    `GET /api/assets/{id}/versions` but without author e-mail domains (a
    public link reaches the internet). Not counted as a view."""
    share, asset = await _resolve_share(token, session)
    await _assert_share_view(request, share, asset, session, settings)
    return await version_rows(session, asset)


@router.get("/api/share/{token}/doc")
async def share_doc(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    version: VersionParam = None,
) -> dict:
    """Document content behind the link. Only the current version counts as
    a view; archived previews (`?version=N`) don't spend `max_views`."""
    from app.routes.assets import _doc_payload_for

    share, asset = await _resolve_share(token, session)
    role = await _assert_share_view(request, share, asset, session, settings, need_role=True)
    if documents.renders_inline(asset.kind) and role is None:
        # The payload is the document's content (`html`): withheld from
        # guests while the document awaits review, like PDF bytes.
        from app.routes.assets import assert_bundle_renderable_for_visitors

        assert_bundle_renderable_for_visitors(asset)

    # Explicitly without security_report: an anonymous visitor doesn't get the
    # scanner finding details.
    payload = await _doc_payload_for(
        asset,
        settings,
        session=session,
        include_security_report=False,
        version=version,
    )
    # Only a successor this visitor can open: a guest must not learn about
    # a newer document they have no way into.
    payload["superseded_by"] = await superseded.for_share(
        session, await _identity(request, session, settings), asset, settings.allowed_domain_list
    )
    # The view is counted here for Markdown and documents (`/pdf` is not
    # counted), at `/html-grant` for bundles. Role holders are not guests of
    # the link and never spend `max_views`.
    if (
        role is None
        and (asset.kind in ("md_single", "md_collection") or documents.is_document(asset.kind))
        and payload["preview_version"] is None
    ):
        await _increment_view_count(session, share.id)
        await session.commit()
    return payload


@router.get("/api/share/{token}/download")
async def share_download(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    """Visitor download of the source files, gated by the same admin review
    as the rendered view: the source is the same content."""
    from app.routes.assets import _stream_source, assert_bundle_renderable_for_visitors

    share, asset = await _resolve_share(token, session)
    await _assert_share_view(request, share, asset, session, settings)
    assert_bundle_renderable_for_visitors(asset)
    return await _stream_source(asset, settings)


@router.get("/api/share/{token}/pdf")
async def share_pdf(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    version: VersionParam = None,
) -> Response:
    """The PDF behind the link, for the viewer. Gated like `/download`: a
    PDF held for admin review (critical scan) is withheld from visitors."""
    from app.routes.assets import assert_bundle_renderable_for_visitors
    from app.routes.assets.documents import assert_pdf, pdf_response

    share, asset = await _resolve_share(token, session)
    await _assert_share_view(request, share, asset, session, settings)
    assert_pdf(asset)
    assert_bundle_renderable_for_visitors(asset)
    return await pdf_response(asset, resolve_version_or_404(asset, version), settings)


@router.get("/api/share/{token}/file")
async def share_file(
    token: str,
    path: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    version: VersionParam = None,
) -> dict:
    from app.routes.assets._helpers import render_collection_file

    share, asset = await _resolve_share(token, session)
    await _assert_share_view(request, share, asset, session, settings)
    return await render_collection_file(asset, path, version, settings)


@router.get("/api/share/{token}/graph")
async def share_graph(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    """Wikilink graph of a shared md_collection: file names and titles only,
    no more sensitive than the file tree."""
    from app.graph import build_graph

    share, asset = await _resolve_share(token, session)
    await _assert_share_view(request, share, asset, session, settings)
    if asset.kind != "md_collection":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "collection_only",
            "graph available only for vaults (md_collection)",
        )
    return await build_graph(asset, settings)


@router.get("/api/share/{token}/html-grant")
async def share_html_grant(
    token: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    version: VersionParam = None,
) -> dict:
    """Grant URL for the isolated viewer, after the share-mode check.

    The view is counted here for bundles; the 1 h cookie lets a visitor of a
    `max_views=1` link browse the bundle until it expires. Archived versions
    don't count.
    """
    from app.routes.assets import assert_bundle_renderable_for_visitors
    from app.routes.html_viewer import issue_grant

    share, asset = await _resolve_share(token, session)
    role = await _assert_share_view(request, share, asset, session, settings, need_role=True)
    if asset.kind != "html_bundle":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "not_html_bundle", "the document is not an HTML bundle"
        )
    assert_bundle_renderable_for_visitors(asset)
    v = resolve_version_or_404(asset, version)
    stale = v != asset.version
    successor = (
        None
        if stale
        else await superseded.for_share(
            session,
            await _identity(request, session, settings),
            asset,
            settings.allowed_domain_list,
        )
    )
    sig = issue_grant(
        asset.id,
        version=v if stale else None,
        successor_href=successor["href"] if successor else None,
    )
    if not stale and role is None:
        await _increment_view_count(session, share.id)
        await session.commit()
    return {"url": f"{settings.html_viewer_base}/_/grant?t={sig}"}


@router.get("/api/share/{token}/static/{path:path}")
async def share_static(
    token: str,
    path: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    from app.routes.assets import assert_bundle_renderable_for_visitors, serve_bundle_file

    share, asset = await _resolve_share(token, session)
    await _assert_share_view(request, share, asset, session, settings)
    assert_bundle_renderable_for_visitors(asset)
    return await serve_bundle_file(
        asset, path, settings, session=session, request=request, app_origin=True
    )
