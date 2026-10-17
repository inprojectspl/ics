"""Reader entry points: the document payload and the HTML bundle grant.

Both carry the successor of a superseded document the reader can open, so the
reader and the isolated HTML viewer show the same banner.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.routes._version_param import VersionParam, resolve_version_or_404
from app.routes.assets._helpers import _doc_payload_for
from app.routes.assets.view import _gate_bundle_for_read_only, router
from app.services import documents, link_resolution, superseded
from app.services.sharing import build_asset_url


@router.get("/by-slug/{slug}/html-grant")
async def asset_html_grant(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    version: VersionParam = None,
) -> dict:
    """Signed grant URL for the isolated viewer (viewer level). Auth is checked
    here; a critical bundle is still stopped by the visitor gate when served."""
    from app.routes.html_viewer import issue_grant

    asset, _ = await permissions.get_viewable_asset_by_slug(session, slug, user)
    if asset.kind != "html_bundle":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "not_html_bundle", "the document is not an HTML bundle"
        )
    v = resolve_version_or_404(asset, version)
    current = v == asset.version
    successor = await superseded.for_viewer(session, user, asset) if current else None
    sig = issue_grant(
        asset.id,
        version=None if current else v,
        successor_href=successor["href"] if successor else None,
    )
    return {"url": f"{settings.html_viewer_base}/_/grant?t={sig}"}


@router.get("/by-slug/{slug}/doc")
async def get_doc(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    version: VersionParam = None,
    accept_language: AcceptLanguage = None,
) -> dict:
    """Document payload for the viewer (`/v/<slug>`), for every collaborator.

    `my_role` drives the edit actions in the UI; `security_report` is editor+
    only. `?version=N` is a read-only preview.
    """
    asset, role = await permissions.get_viewable_asset_by_slug(session, slug, user)
    if documents.renders_inline(asset.kind):
        # The payload carries the document's content (`html`), so a document
        # held for review is withheld from read-only roles like the bytes.
        _gate_bundle_for_read_only(role, asset)
    payload = await _doc_payload_for(
        asset,
        settings,
        session=session,
        include_security_report=not permissions.is_read_only(role),
        version=version,
        locale=resolve_locale(user.locale, accept_language=accept_language),
    )
    payload["my_role"] = role
    payload["superseded_by"] = await superseded.for_viewer(session, user, asset)
    # The viewer rewrites its address bar to this, since people paste it into
    # chat. The `/s/<token>` form only goes to roles that may share externally
    # anyway; others would otherwise redistribute access they cannot grant.
    payload["canonical_url"] = (
        await link_resolution.canonical_url(session, settings, asset)
        if permissions.can_share_externally(role)
        else build_asset_url(settings, asset.slug)
    )
    return payload
