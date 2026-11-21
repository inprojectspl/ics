"""Isolated HTML viewer with copyable addresses: the link kept in the page
address (`ics_share`), the injected bootstrap and the entry page."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app import tokens
from app.config import get_settings
from app.models import ShareLink
from app.routes.html_viewer import issue_grant, share_basis, user_basis
from app.services.share_context import script_version
from app.slug import generate_token
from tests.conftest import login_as, mk_asset, mk_user, put_blob

NAV = {"Accept": "text/html,application/xhtml+xml"}
PAGE = b'<!doctype html><html><head><meta charset="utf-8"><title>R</title><script src="app.js"></script></head><body><h1>Secret</h1></body></html>'


async def _bundle(session):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle", entry_path="index.html")
    await session.commit()
    for rel in ("index.html", "sub/page.html"):
        await put_blob(asset, rel, PAGE)
    return user, asset


async def _share(session, asset, **kw) -> ShareLink:
    share = ShareLink(asset_id=asset.id, token=generate_token(), mode="public", **kw)
    session.add(share)
    await session.commit()
    return share


async def _open(client, grant: str):
    r = await client.get(f"/html/_/grant?t={grant}", follow_redirects=False)
    assert r.status_code == 302
    return r


@pytest.mark.asyncio
async def test_share_grant_lands_on_the_target_with_the_link(client, session, fs_storage):
    _, asset = await _bundle(session)
    share = await _share(session, asset)
    r = await client.get(
        f"/api/share/{share.token}/html-grant",
        params={"to": f"sub/page.html?tab=2&ics_share={'X' * 43}"},
    )
    landed = await _open(client, parse_qs(urlparse(r.json()["url"]).query)["t"][0])
    assert landed.headers["location"] == (
        f"/{asset.slug}/sub/page.html?tab=2&ics_share={share.token}"
    )
    # A link entry is not an open from the panel.
    assert "ics_html_entry" not in landed.headers.get("set-cookie", "")


@pytest.mark.asyncio
@pytest.mark.parametrize("to", ["../other/index.html", "//evil.example/", "%2e%2e/x.html"])
async def test_grant_target_never_leaves_the_bundle(client, session, fs_storage, to):
    _, asset = await _bundle(session)
    share = await _share(session, asset)
    r = await client.get(f"/api/share/{share.token}/html-grant", params={"to": to})
    landed = await _open(client, parse_qs(urlparse(r.json()["url"]).query)["t"][0])
    assert landed.headers["location"] == f"/{asset.slug}/index.html?ics_share={share.token}"


@pytest.mark.asyncio
async def test_role_holder_grant_keeps_the_opened_link(client, session, fs_storage):
    user, asset = await _bundle(session)
    share = await _share(session, asset)
    await login_as(client, user)
    r = await client.get(
        f"/api/assets/by-slug/{asset.slug}/html-grant",
        params={"share": share.token, "to": "sub/page.html"},
    )
    assert r.status_code == 200, r.text
    landed = await _open(client, parse_qs(urlparse(r.json()["url"]).query)["t"][0])
    assert landed.headers["location"] == f"/{asset.slug}/sub/page.html?ics_share={share.token}"

    _, other = await _bundle(session)
    foreign = await _share(session, other)
    r = await client.get(
        f"/api/assets/by-slug/{asset.slug}/html-grant", params={"share": foreign.token}
    )
    assert r.status_code == 404 and r.json()["code"] == "share_not_found"


@pytest.mark.asyncio
async def test_panel_open_marks_a_direct_entry_once(client, session, fs_storage):
    user, asset = await _bundle(session)
    landed = await _open(client, issue_grant(asset.id, basis=user_basis(user.id)))
    assert landed.headers["location"] == f"/{asset.slug}/index.html"
    cookie = landed.headers["set-cookie"]
    assert "ics_html_entry=" in cookie and f"Path=/{asset.slug}/" in cookie
    launch = cookie.split("ics_html_entry=", 1)[1].split(";", 1)[0]

    # The browser sends the marker to the asset's pages (`/{slug}/`, which the
    # proxy maps to `/html/{slug}/`).
    client.cookies.set("ics_html_entry", launch)
    page = await client.get(f"/html/{asset.slug}/index.html")
    assert page.status_code == 200
    assert 'data-entry-mode="direct"' in page.text and f'data-launch="{launch}"' in page.text
    assert 'ics_html_entry=""' in page.headers["set-cookie"]


@pytest.mark.asyncio
async def test_old_grants_without_the_link_fields_still_open(client, session, fs_storage):
    user, asset = await _bundle(session)
    legacy = tokens.issue("html_grant", f"{asset.id}||{user_basis(user.id)}")
    landed = await _open(client, legacy)
    assert landed.headers["location"] == f"/{asset.slug}/index.html"


@pytest.mark.asyncio
async def test_pages_get_the_bootstrap_first_and_files_stay_untouched(
    client, session, fs_storage, monkeypatch
):
    _, asset = await _bundle(session)
    share = await _share(session, asset)
    await put_blob(asset, "app.js", b"console.log(1)")
    await _open(client, issue_grant(asset.id, basis=share_basis(share.id), share_token=share.token))

    r = await client.get(f"/html/{asset.slug}/index.html", params={"ics_share": share.token})
    assert r.status_code == 200
    body = r.content
    tag = body.index(b'<script src="' + get_settings().html_viewer_base.encode())
    assert body.index(b"<meta charset") < tag < body.index(b"<title>") < body.index(b"app.js")
    assert b'data-entry-mode="continuation"' in body
    assert f'data-scope="/{asset.slug}/"'.encode() in body
    assert int(r.headers["content-length"]) == len(body)
    assert r.headers["cache-control"] == "no-store"
    js = await client.get(f"/html/{asset.slug}/app.js")
    assert js.content == b"console.log(1)"

    # The platform switch stops the injection, not the copied addresses.
    monkeypatch.setattr(get_settings(), "share_context_enabled", False)
    off = await client.get(f"/html/{asset.slug}/index.html", params={"ics_share": share.token})
    assert off.status_code == 200 and b"data-entry-mode" not in off.content


@pytest.mark.asyncio
async def test_no_grant_gets_the_entry_page_without_content(client, session, fs_storage):
    _, asset = await _bundle(session)
    r = await client.get(f"/html/{asset.slug}/sub/page.html", headers=NAV)
    assert r.status_code == 401
    assert "Secret" not in r.text
    assert 'data-entry-mode="recover"' in r.text
    assert "/s/{token}?to={to}" in r.text
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["referrer-policy"] == "no-referrer"
    # A fetch, not a page load: the plain API error as before.
    api = await client.get(f"/html/{asset.slug}/sub/page.html")
    assert api.status_code == 401 and api.json()["code"] == "grant_required"


@pytest.mark.asyncio
async def test_archived_entry_page_resumes_the_same_version(client, session, fs_storage):
    _, asset = await _bundle(session)
    asset.version = 2
    await session.commit()
    await put_blob(asset, "index.html", PAGE)
    r = await client.get(f"/html/-v1/{asset.slug}/index.html", headers=NAV)
    assert r.status_code == 401 and "/s/{token}?ver=1&amp;to={to}" in r.text


@pytest.mark.asyncio
async def test_another_link_in_the_address_is_a_new_entry(client, session, fs_storage):
    _, asset = await _bundle(session)
    mine, other = await _share(session, asset), await _share(session, asset)
    await _open(client, issue_grant(asset.id, basis=share_basis(mine.id), share_token=mine.token))
    url = f"/html/{asset.slug}/index.html"

    assert (await client.get(url, params={"ics_share": mine.token}, headers=NAV)).status_code == 200
    # The cookie of link A does not approve a visit through link B.
    crossed = await client.get(url, params={"ics_share": other.token}, headers=NAV)
    assert crossed.status_code == 401 and "Secret" not in crossed.text
    # Without a token the visit continues (the script restores it).
    assert (await client.get(url, headers=NAV)).status_code == 200
    # Repeated parameter: refused, and the entry page does not pick a link.
    twice = await client.get(f"{url}?ics_share={mine.token}&ics_share={mine.token}", headers=NAV)
    assert twice.status_code == 400 and "Secret" not in twice.text


@pytest.mark.asyncio
async def test_member_keeps_own_access_but_the_link_must_be_of_this_asset(
    client, session, fs_storage
):
    user, asset = await _bundle(session)
    share = await _share(session, asset)
    _, other = await _bundle(session)
    foreign = await _share(session, other)
    await _open(client, issue_grant(asset.id, basis=user_basis(user.id), share_token=share.token))
    url = f"/html/{asset.slug}/index.html"
    assert (
        await client.get(url, params={"ics_share": share.token}, headers=NAV)
    ).status_code == 200
    bad = await client.get(url, params={"ics_share": foreign.token}, headers=NAV)
    assert bad.status_code == 401 and "Secret" not in bad.text


@pytest.mark.asyncio
async def test_spent_link_serves_the_granted_visit_without_new_views(client, session, fs_storage):
    _, asset = await _bundle(session)
    share = await _share(session, asset, max_views=1)
    r = await client.get(f"/api/share/{share.token}/html-grant")
    await _open(client, parse_qs(urlparse(r.json()["url"]).query)["t"][0])
    for path in ("index.html", "sub/page.html", "index.html"):
        page = await client.get(f"/html/{asset.slug}/{path}", params={"ics_share": share.token})
        assert page.status_code == 200
    await session.refresh(share)
    assert share.view_count == 1
    # A new entry through the spent link is refused as before.
    assert (await client.get(f"/api/share/{share.token}/html-grant")).status_code == 410


@pytest.mark.asyncio
async def test_revoked_link_ends_the_visit(client, session, fs_storage):
    from datetime import UTC, datetime

    _, asset = await _bundle(session)
    share = await _share(session, asset)
    await _open(client, issue_grant(asset.id, basis=share_basis(share.id), share_token=share.token))
    share.revoked_at = datetime.now(UTC)
    await session.commit()
    r = await client.get(
        f"/html/{asset.slug}/index.html", params={"ics_share": share.token}, headers=NAV
    )
    assert r.status_code == 401 and "Secret" not in r.text


@pytest.mark.asyncio
async def test_script_is_served_with_a_validator(client):
    r = await client.get("/html/_/share-context.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    assert b"ics_share" in r.content
    again = await client.get(
        "/html/_/share-context.js", headers={"If-None-Match": r.headers["etag"]}
    )
    assert again.status_code == 304
    # Pages ask for it by content hash, which may be kept for good.
    pinned = await client.get(f"/html/_/share-context.js?v={script_version()}")
    assert "immutable" in pinned.headers["cache-control"]
