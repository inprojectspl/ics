"""Asset -> share link resolver (`services.notifications._link_resolver`).

DB-backed. Checks:
- org_sso is preferred over public,
- revoked / expired links are skipped,
- None when there are no active share links,
- token -> URL mapping with `settings.base_url`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.config import get_settings
from app.models import ShareLink
from app.services.notifications._link_resolver import resolve_asset_share_link
from app.services.notifications._types import AssetLinkVisibility
from app.slug import generate_token
from tests.conftest import mk_asset, mk_user


def _mk_share(
    asset_id,
    mode: str,
    *,
    token: str | None = None,
    revoked: bool = False,
    expired: bool = False,
) -> ShareLink:
    return ShareLink(
        asset_id=asset_id,
        token=token or generate_token(),
        mode=mode,
        revoked_at=datetime.now(UTC) if revoked else None,
        expires_at=(datetime.now(UTC) - timedelta(hours=1) if expired else None),
    )


@pytest.mark.asyncio
async def test_prefers_org_sso_over_public(session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    session.add_all(
        [
            _mk_share(asset.id, "public", token="pub-tok"),
            _mk_share(asset.id, "org_sso", token="org-tok"),
        ]
    )
    await session.commit()

    link = await resolve_asset_share_link(session, asset.id, get_settings())
    assert link is not None
    assert link.visibility is AssetLinkVisibility.ORG
    assert link.url.endswith("/s/org-tok")


@pytest.mark.asyncio
async def test_falls_back_to_public_when_no_org(session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    session.add(_mk_share(asset.id, "public", token="pub-only"))
    await session.commit()

    link = await resolve_asset_share_link(session, asset.id, get_settings())
    assert link is not None
    assert link.visibility is AssetLinkVisibility.PUBLIC
    assert link.url.endswith("/s/pub-only")


@pytest.mark.asyncio
async def test_skips_revoked_org_then_uses_public(session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    session.add_all(
        [
            _mk_share(asset.id, "org_sso", token="org-revoked", revoked=True),
            _mk_share(asset.id, "public", token="pub-active"),
        ]
    )
    await session.commit()

    link = await resolve_asset_share_link(session, asset.id, get_settings())
    assert link is not None
    assert link.visibility is AssetLinkVisibility.PUBLIC
    assert link.url.endswith("/s/pub-active")


@pytest.mark.asyncio
async def test_skips_expired(session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    session.add(_mk_share(asset.id, "org_sso", expired=True))
    await session.commit()

    link = await resolve_asset_share_link(session, asset.id, get_settings())
    assert link is None


@pytest.mark.asyncio
async def test_ignores_non_org_public_modes(session):
    """`password` / `magic_email` shares are skipped: they would require
    extra steps from the notification recipient."""
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    session.add_all(
        [
            _mk_share(asset.id, "password"),
            _mk_share(asset.id, "magic_email"),
        ]
    )
    await session.commit()

    link = await resolve_asset_share_link(session, asset.id, get_settings())
    assert link is None


@pytest.mark.asyncio
async def test_returns_none_when_no_shares(session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()

    link = await resolve_asset_share_link(session, asset.id, get_settings())
    assert link is None
