"""Superseded banner: the reader payload, the share payload and the HTML
bundle all point at the successor only when this visitor can open it."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest

from app.models import AssetRelation, AssetShare, ShareLink
from app.slug import generate_token
from tests.conftest import login_as, mk_asset, mk_user, put_blob

PAGE = b"<html><head><title>x</title></head><body><h1>Old</h1></body></html>"


def _supersedes(new, old) -> AssetRelation:
    return AssetRelation(
        source_asset_id=new.id,
        target_asset_id=old.id,
        relation_type="supersedes",
        origin="manual",
    )


async def _open_bundle(client, slug: str, accept_language: str) -> str:
    """Reader grant -> iso viewer grant (sets the cookie) -> entry page."""
    r = await client.get(f"/api/assets/by-slug/{slug}/html-grant")
    assert r.status_code == 200
    token = parse_qs(urlparse(r.json()["url"]).query)["t"][0]
    r = await client.get(f"/html/_/grant?t={token}", follow_redirects=False)
    assert r.status_code == 302
    r = await client.get(f"/html/{slug}/index.html", headers={"Accept-Language": accept_language})
    assert r.status_code == 200
    return r.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("accept_language", "expected"),
    [("pl-PL,pl;q=0.9", "Otw&#243;rz aktualny dokument"), ("en-US", "Open the current document")],
)
async def test_bundle_banner_for_superseded_bundle(
    client, session, fs_storage, accept_language, expected
):
    owner = await mk_user(session)
    old = await mk_asset(session, owner, kind="html_bundle", entry_path="index.html")
    new = await mk_asset(session, owner, title="Spec v3")
    session.add(_supersedes(new, old))
    await session.commit()
    await put_blob(old, "index.html", PAGE)
    await login_as(client, owner)

    page = await _open_bundle(client, old.slug, accept_language)
    assert 'id="ics-superseded-banner"' in page
    assert expected in page
    assert "Spec v3" in page
    assert f"/v/{new.slug}" in page
    assert page.index("ics-superseded-banner") > page.index("<body>")


@pytest.mark.asyncio
async def test_bundle_banner_absent_when_successor_is_hidden(client, session, fs_storage):
    owner = await mk_user(session)
    reader = await mk_user(session)
    other = await mk_user(session)
    old = await mk_asset(session, owner, kind="html_bundle", entry_path="index.html")
    hidden = await mk_asset(session, other, title="Secret successor")
    session.add_all(
        [
            _supersedes(hidden, old),
            AssetShare(asset_id=old.id, user_id=reader.id, role="viewer"),
        ]
    )
    await session.commit()
    await put_blob(old, "index.html", PAGE)
    await login_as(client, reader)

    page = await _open_bundle(client, old.slug, "en")
    assert "ics-superseded-banner" not in page
    assert "Secret successor" not in page


@pytest.mark.asyncio
async def test_share_payload_hides_successor_without_access(client, session, fs_storage):
    owner = await mk_user(session)
    old = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    new = await mk_asset(session, owner, title="Newer")
    link = ShareLink(asset_id=old.id, token=generate_token(), mode="public", created_by=owner.id)
    session.add_all([link, _supersedes(new, old)])
    await session.commit()
    await put_blob(old, "doc.md", b"# Old\n")

    # Anonymous guest, successor has no link they could use.
    r = await client.get(f"/api/share/{link.token}/doc")
    assert r.status_code == 200
    assert r.json()["superseded_by"] is None
    assert "Newer" not in r.text

    # A password link on the successor does not count: it needs a challenge.
    session.add(
        ShareLink(asset_id=new.id, token=generate_token(), mode="password", created_by=owner.id)
    )
    await session.commit()
    r = await client.get(f"/api/share/{link.token}/doc")
    assert r.json()["superseded_by"] is None

    # A public link on the successor: the guest can open it.
    public = ShareLink(asset_id=new.id, token=generate_token(), mode="public", created_by=owner.id)
    session.add(public)
    await session.commit()
    r = await client.get(f"/api/share/{link.token}/doc")
    succ = r.json()["superseded_by"]
    assert succ["href"] == f"/s/{public.token}"
    assert succ["title"] == "Newer"


@pytest.mark.asyncio
async def test_signed_in_share_viewer_with_role_goes_to_viewer(client, session, fs_storage):
    owner = await mk_user(session)
    colleague = await mk_user(session)
    old = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    new = await mk_asset(session, owner)
    link = ShareLink(asset_id=old.id, token=generate_token(), mode="public", created_by=owner.id)
    session.add_all(
        [
            link,
            _supersedes(new, old),
            AssetShare(asset_id=new.id, user_id=colleague.id, role="viewer"),
        ]
    )
    await session.commit()
    await put_blob(old, "doc.md", b"# Old\n")
    await login_as(client, colleague)

    r = await client.get(f"/api/share/{link.token}/doc")
    assert r.json()["superseded_by"]["href"] == f"/v/{new.slug}"


@pytest.mark.asyncio
async def test_reader_payload_carries_visible_successor(client, session, fs_storage):
    owner = await mk_user(session)
    old = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    new = await mk_asset(session, owner, title="Current")
    session.add(_supersedes(new, old))
    await session.commit()
    await put_blob(old, "doc.md", b"# Old\n")
    await put_blob(new, "doc.md", b"# New\n")
    await login_as(client, owner)

    r = await client.get(f"/api/assets/by-slug/{old.slug}/doc")
    succ = r.json()["superseded_by"]
    assert succ["slug"] == new.slug
    assert succ["href"] == f"/v/{new.slug}"
    assert succ["since"]
    r = await client.get(f"/api/assets/by-slug/{new.slug}/doc")
    assert r.json()["superseded_by"] is None
