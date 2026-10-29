"""An access cookie of the isolated HTML viewer ends with what authorized it:
a revoked link, a removed share or a locked account stop the next request, and
opening another document never extends an old entry."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from app.models import AssetShare, ShareLink
from app.slug import generate_token
from tests.conftest import login_as, mk_asset, mk_html_bundle, mk_user, put_blob


async def _bundle(session, owner, title="Report"):
    asset = await mk_asset(session, owner, title=title, kind="html_bundle", entry_path="index.html")
    await put_blob(asset, "index.html", b"<html><body>v1</body></html>")
    return asset


async def _open(client, grant_path: str) -> None:
    """App or share grant -> isolated viewer grant, which sets the cookie."""
    r = await client.get(grant_path)
    assert r.status_code == 200, r.text
    token = parse_qs(urlparse(r.json()["url"]).query)["t"][0]
    r = await client.get(f"/html/_/grant?t={token}", follow_redirects=False)
    assert r.status_code == 302


async def _read(client, asset) -> int:
    return (await client.get(f"/html/{asset.slug}/index.html")).status_code


async def _public_link(session, asset, owner, **kw) -> ShareLink:
    link = ShareLink(
        asset_id=asset.id, token=generate_token(), mode="public", created_by=owner.id, **kw
    )
    session.add(link)
    await session.commit()
    return link


@pytest.mark.asyncio
async def test_revoked_link_stops_the_cookie_also_for_a_later_version(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _bundle(session, owner)
    link = await _public_link(session, asset, owner)

    await _open(client, f"/api/share/{link.token}/html-grant")
    assert await _read(client, asset) == 200

    link.revoked_at = datetime.now(UTC)
    asset.version = 2
    await session.commit()
    await put_blob(asset, "index.html", b"<html><body>v2, never shared</body></html>")
    assert await _read(client, asset) == 401


@pytest.mark.asyncio
async def test_expired_link_stops_the_cookie(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _bundle(session, owner)
    link = await _public_link(session, asset, owner)
    await _open(client, f"/api/share/{link.token}/html-grant")

    link.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    assert await _read(client, asset) == 401


@pytest.mark.asyncio
async def test_a_single_view_link_serves_the_visit_it_counted(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _bundle(session, owner)
    link = await _public_link(session, asset, owner, max_views=1)

    await _open(client, f"/api/share/{link.token}/html-grant")
    await session.refresh(link)
    assert link.view_count == 1
    assert await _read(client, asset) == 200


@pytest.mark.asyncio
async def test_removed_share_stops_the_cookie(client, session, fs_storage):
    owner = await mk_user(session)
    reader = await mk_user(session)
    asset = await _bundle(session, owner)
    share = AssetShare(asset_id=asset.id, user_id=reader.id, role="viewer")
    session.add(share)
    await session.commit()
    await login_as(client, reader)

    await _open(client, f"/api/assets/by-slug/{asset.slug}/html-grant")
    assert await _read(client, asset) == 200

    await session.delete(share)
    await session.commit()
    assert await _read(client, asset) == 401


@pytest.mark.asyncio
async def test_locked_account_stops_the_cookie(client, session, fs_storage):
    owner, asset = await mk_html_bundle(client, session, {"index.html": b"<html>v1</html>"})
    await _open(client, f"/api/assets/by-slug/{asset.slug}/html-grant")

    owner.locked_until = datetime.now(UTC) + timedelta(hours=1)
    await session.commit()
    assert await _read(client, asset) == 401


@pytest.mark.asyncio
async def test_opening_another_document_does_not_extend_an_old_entry(client, session, fs_storage):
    owner = await mk_user(session)
    first = await _bundle(session, owner, title="First")
    second = await _bundle(session, owner, title="Second")
    await session.commit()
    await login_as(client, owner)

    start = datetime.now(UTC).timestamp()
    with patch("app.routes.html_viewer.time.time", return_value=start):
        await _open(client, f"/api/assets/by-slug/{first.slug}/html-grant")
    with patch("app.routes.html_viewer.time.time", return_value=start + 3500):
        await _open(client, f"/api/assets/by-slug/{second.slug}/html-grant")
    with patch("app.routes.html_viewer.time.time", return_value=start + 3700):
        assert await _read(client, first) == 401
        assert await _read(client, second) == 200
