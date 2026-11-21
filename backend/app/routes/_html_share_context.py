"""Share-link context on the isolated HTML viewer: the bootstrap element of a
served page and the entry page shown instead of a document without a grant
(`services/share_context.py`, docs/copyable-addresses.md)."""

from __future__ import annotations

import re

from fastapi import Request, Response, status

from app.config import Settings
from app.i18n import resolve_locale, t
from app.models import Asset
from app.routes.assets._helpers import _static_headers
from app.services import share_context
from app.services.sharing import build_app_url

#: One-shot marker of an open from the ICS panel without a share link, set by
#: `/_/grant` for the asset's pages; the next page passes it to the script as
#: a direct entry, which drops the tab's earlier link context.
ENTRY_COOKIE = "ics_html_entry"
ENTRY_COOKIE_MAX_AGE_S = 60
_LAUNCH_RE = re.compile(r"[A-Za-z0-9_-]{8,32}")


def scope_of(asset: Asset, version: int | None) -> str:
    """URL prefix of the asset's pages (current or archived version)."""
    return f"/{asset.slug}/" if version is None else f"/-v{version}/{asset.slug}/"


def is_navigation(request: Request) -> bool:
    """A page load in the browser, not a fetch of the bundle's own code."""
    if request.headers.get("sec-fetch-dest") == "document":
        return True
    return "text/html" in request.headers.get("accept", "")


def _tag(settings: Settings, asset: Asset, version: int | None, **entry: str | None) -> str:
    # The version in the address lets browsers keep the script for good.
    base = settings.html_viewer_base.rstrip("/")
    return share_context.script_tag(
        f"{base}/_/share-context.js?v={share_context.script_version()}",
        asset_id=str(asset.id),
        kind="html_bundle",
        scope=scope_of(asset, version),
        **entry,
    )


def page_tag(settings: Settings, request: Request, asset: Asset, version: int | None) -> str:
    """The element for a served page; a valid panel marker makes it a direct
    entry (the caller deletes the cookie)."""
    launch = request.cookies.get(ENTRY_COOKIE)
    if launch is not None and _LAUNCH_RE.fullmatch(launch):
        return _tag(settings, asset, version, entry_mode="direct", launch=launch)
    return _tag(settings, asset, version, entry_mode="continuation")


def recovery_response(
    settings: Settings,
    asset: Asset,
    version: int | None,
    *,
    invalid: bool,
    accept_language: str | None,
) -> Response:
    """Entry page without the asset's content: the script resumes the visit
    through the link in the address or the tab's context, else the page
    asks to open the document from its link."""
    # The ICS origin this viewer belongs to, not `share_base_url`: that one
    # may point at a tunnel for addresses handed out elsewhere.
    share_page = build_app_url(settings, "/s/{token}")
    query = f"ver={version}&to={{to}}" if version is not None else "to={to}"
    tag = _tag(
        settings, asset, version, entry_mode="recover", recover_share=f"{share_page}?{query}"
    )
    locale = resolve_locale(accept_language=accept_language)
    body = share_context.recovery_page(
        lang=locale,
        title=t("share_context.recover_title", locale),
        message=t("share_context.recover_body", locale),
        script_html=tag,
    )
    csp = (
        f"default-src 'none'; script-src {settings.html_viewer_origin}; "
        "base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
    )
    return Response(
        content=body,
        status_code=status.HTTP_400_BAD_REQUEST if invalid else status.HTTP_401_UNAUTHORIZED,
        media_type="text/html; charset=utf-8",
        headers=_static_headers(csp, rel_path="entry.html"),
    )
