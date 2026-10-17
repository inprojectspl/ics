"""Cross-origin viewer for html_bundle assets, served on its own subdomain so
bundle JS cannot reach the main app's cookies or API. The main app signs a
short-lived grant; `/_/grant` turns it into the `ics_html_access` cookie that
every later request inside the bundle carries."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import tokens
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import Asset
from app.routes._version_param import resolve_version_or_404
from app.services.versions import entry_path_at_version, version_created_at

router = APIRouter(prefix="/html", tags=["html-viewer"], include_in_schema=False)

COOKIE_NAME = "ics_html_access"
COOKIE_MAX_AGE_S = 60 * 60
# Keeps the cookie well under the browser's ~4 KB limit (~37 chars per entry).
MAX_GRANTED_PER_COOKIE = 32


# ---------- access cookie ----------


def _read_granted(request: Request) -> set[str]:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return set()
    try:
        payload = tokens.verify("html_access_cookie", raw)
    except tokens.TokenInvalid:
        return set()
    return {s for s in payload.split(",") if s}


def _sign_granted(ids: set[str]) -> str:
    return tokens.issue("html_access_cookie", ",".join(sorted(ids)))


def grant_key(asset_id: UUID | str, version: int | None) -> str:
    """Cookie / grant entry: bare UUID for the current version, `"{uuid}:{N}"`
    for an archived one, so neither grant opens the other."""
    return f"{asset_id}:{version}" if version is not None else str(asset_id)


# Cookie entry `sup:{asset_id}={href}`: the successor this visitor may open,
# decided on the ICS origin when the grant was issued (this origin has no
# session). Refreshed by every grant of the current version.
_SUCCESSOR_PREFIX = "sup:"


def _successor_key(asset_id: UUID | str) -> str:
    return f"{_SUCCESSOR_PREFIX}{asset_id}="


def issue_grant(
    asset_id: UUID, version: int | None = None, *, successor_href: str | None = None
) -> str:
    """Sign a short-lived grant; the caller has already authorized the visitor.

    `version` is None for the current version. `successor_href` (current
    version only) is a successor the caller checked this visitor may open;
    the entry page then carries the superseded banner."""
    key = grant_key(asset_id, version)
    if successor_href and version is None:
        key = f"{key}|{successor_href}"
    return tokens.issue("html_grant", key)


def _parse_grant(payload: str) -> tuple[UUID, int | None, str | None]:
    """`"uuid"` -> (uuid, None, None); `"uuid:3"` -> (uuid, 3, None);
    `"uuid|/v/slug"` -> (uuid, None, "/v/slug"). Raises ValueError on
    garbage; the caller maps it to 400 (the signature may be valid while
    the format comes from another app version)."""
    key, _, successor = payload.partition("|")
    raw_id, _, raw_v = key.partition(":")
    return UUID(raw_id), int(raw_v) if raw_v else None, successor or None


# ---------- endpoints ----------


@router.get("/_/grant", response_class=RedirectResponse)
async def grant(
    t: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    try:
        payload = tokens.verify("html_grant", t)
    except tokens.TokenExpired:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "link_expired", "link expired") from None
    except tokens.TokenInvalid:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "link_invalid", "invalid link") from None

    try:
        asset_id, version, successor = _parse_grant(payload)
    except ValueError:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "link_invalid", "invalid link") from None

    asset = await session.get(Asset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.kind != "html_bundle":
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")

    v = resolve_version_or_404(asset, version)
    entry = await entry_path_at_version(asset, v, settings)
    prefix = f"/{asset.slug}" if version is None else f"/-v{v}/{asset.slug}"

    target = f"{prefix}/{entry}" if entry else f"{prefix}/"
    response = RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)

    key = grant_key(asset.id, version)
    old = _read_granted(request)
    granted = set(old)
    granted.add(key)
    if version is None:
        granted = {g for g in granted if not g.startswith(_successor_key(asset.id))}
        if successor:
            granted.add(_successor_key(asset.id) + successor)
    if granted == old:
        return response

    if len(granted) > MAX_GRANTED_PER_COOKIE:
        # Alphabetical trim (the cookie has no recency); the key just granted
        # is kept explicitly, since a plain slice could drop it.
        keep = MAX_GRANTED_PER_COOKIE - 1
        granted = {key} | set(sorted(granted - {key})[-keep:])

    response.set_cookie(
        COOKIE_NAME,
        _sign_granted(granted),
        max_age=COOKIE_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        # secure=True enforces HTTPS in prod; in dev (*.localhost over HTTP)
        # it stays False, and settings.debug is the switch.
        secure=not settings.debug,
        path="/",
    )
    return response


async def _bundle_or_404(slug: str, session: AsyncSession) -> Asset:
    asset = (await session.execute(select(Asset).where(Asset.slug == slug))).scalar_one_or_none()
    if asset is None or asset.deleted_at is not None or asset.kind != "html_bundle":
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    return asset


async def _serve_granted(
    *,
    slug: str,
    path: str,
    version: int | None,
    request: Request,
    session: AsyncSession,
    settings: Settings,
    accept_language: str | None = None,
) -> Response:
    """Cookie gate, then visitor gate, then serve from the version's tree.

    The visitor gate checks the asset status on every request, so it also
    blocks history and catches a bundle turning critical after the grant.
    """
    from app.routes.assets import (
        assert_bundle_renderable_for_visitors,
        is_html_doc,
        serve_bundle_file,
    )
    from app.services.version_banner import build_banner_html

    asset = await _bundle_or_404(slug, session)
    if grant_key(asset.id, version) not in _read_granted(request):
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, "grant_required", "open the document through ICS"
        )
    assert_bundle_renderable_for_visitors(asset)
    v = resolve_version_or_404(asset, version)

    # HTML only: subresources must not pay for the version-date query.
    prelude = None
    if v == asset.version and version is None and is_html_doc(path):
        prelude = await _superseded_prelude(
            asset, _read_granted(request), session, settings, accept_language
        )
    elif v != asset.version and is_html_doc(path):
        prelude = build_banner_html(
            preview_version=v,
            current_version=asset.version,
            preview_created_at=await version_created_at(session, asset, v),
            current_updated_at=asset.updated_at,
            # The isolated origin has no ICS session, only the browser's language.
            locale=resolve_locale(accept_language=accept_language),
        )
    return await serve_bundle_file(
        asset,
        path,
        settings,
        session=session,
        request=request,
        version=version,
        body_prelude=prelude,
    )


async def _superseded_prelude(
    asset: Asset,
    granted: set[str],
    session: AsyncSession,
    settings: Settings,
    accept_language: str | None,
) -> str | None:
    from app.services import superseded
    from app.services.version_banner import build_superseded_banner_html

    prefix = _successor_key(asset.id)
    href = next((g[len(prefix) :] for g in granted if g.startswith(prefix)), None)
    if href is None:
        return None
    succ = await superseded.from_href(session, asset, href)
    if succ is None:
        return None
    since = succ["since"]
    return build_superseded_banner_html(
        title=succ["title"],
        since=datetime.fromisoformat(since) if since else None,
        url=settings.base_url.rstrip("/") + href,
        locale=resolve_locale(accept_language=accept_language),
    )


# Registered before `/{slug}/{path:path}`, which would catch `-v2` as a slug.
# The version is in the path so relative URLs stay inside the archived tree.
@router.get("/-v{n}/{slug}/{path:path}")
async def serve_version(
    n: int,
    slug: str,
    path: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> Response:
    """Read-only preview of an archived bundle version."""
    return await _serve_granted(
        slug=slug,
        path=path,
        version=n,
        request=request,
        session=session,
        settings=settings,
        accept_language=accept_language,
    )


@router.get("/{slug}/{path:path}")
async def serve(
    slug: str,
    path: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> Response:
    return await _serve_granted(
        slug=slug,
        path=path,
        version=None,
        request=request,
        session=session,
        settings=settings,
        accept_language=accept_language,
    )
