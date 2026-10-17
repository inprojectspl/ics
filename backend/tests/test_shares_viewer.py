"""Coverage tests for `routes/shares/viewer.py`: content endpoints behind a share token."""

from __future__ import annotations

import pytest

from app.models import Asset, ShareLink
from app.slug import generate_token
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user, put_blob


async def _mk_public_share(session, asset: Asset) -> ShareLink:
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="public",
    )
    session.add(share)
    await session.flush()
    return share


@pytest.mark.asyncio
async def test_share_doc_returns_md_payload_and_bumps_view_count(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", b"# Hello")
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/doc")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == asset.slug

    # view_count should increase for md_single (md_* kinds are counted
    # in /doc; html_bundle only in /html-grant).
    await session.refresh(share)
    assert share.view_count == 1


@pytest.mark.asyncio
async def test_share_doc_html_bundle_does_not_bump_view_count(client, session, fs_storage):
    """html_bundle /doc returns metadata only: view_count grows only in
    /html-grant. Otherwise max_views=1 would burn out at 0 views."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle", entry_path="index.html")
    await put_blob(asset, "index.html", b"<html><body>hi</body></html>")
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/doc")
    assert r.status_code == 200

    await session.refresh(share)
    assert share.view_count == 0


@pytest.mark.asyncio
async def test_share_file_renders_md_in_collection(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_collection", entry_path="index.md")
    await put_blob(asset, "notes/foo.md", b"# Foo bar")
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/file?path=notes/foo.md")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == asset.slug
    assert body["path"] == "notes/foo.md"
    assert "Foo bar" in body["html"]


@pytest.mark.asyncio
async def test_share_file_rejected_for_md_single(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/file?path=doc.md")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_share_graph_returns_payload_for_collection(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_collection", entry_path="index.md")
    # Storage is needed: build_graph reads the file list.
    await put_blob(asset, "index.md", b"# Idx\n\n[[other]]")
    await put_blob(asset, "other.md", b"# Other")
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/graph")
    assert r.status_code == 200, r.text
    body = r.json()
    # build_graph returns at least a list of nodes. We do not test the
    # wikilink structure (separate test_graph.py), only that the endpoint does not 500.
    assert "nodes" in body
    assert isinstance(body["nodes"], list)


@pytest.mark.asyncio
async def test_share_graph_rejected_for_md_single(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/graph")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_share_html_grant_returns_url_and_bumps_view_count(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle", entry_path="index.html")
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/html-grant")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["url"].startswith("http")
    assert "/_/grant?t=" in body["url"]

    await session.refresh(share)
    assert share.view_count == 1


@pytest.mark.asyncio
async def test_share_html_grant_rejected_for_md_kind(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/html-grant")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_share_html_grant_critical_security_blocks(client, session, fs_storage):
    """Critical security_status without a bypass -> block (assert_bundle_renderable_for_visitors)."""
    user = await mk_user(session)
    asset = await mk_asset(
        session,
        user,
        kind="html_bundle",
        entry_path="index.html",
        security_status="critical",
    )
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/html-grant")
    # 410 Gone: the bundle is held until an admin grants a bypass.
    # (It is deliberately not 403, see the `assert_bundle_renderable_for_visitors` docstring.)
    assert r.status_code == 410


@pytest.mark.asyncio
async def test_share_download_streams_source(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await put_blob(asset, "doc.md", b"# Doc")
    share = await _mk_public_share(session, asset)
    await session.commit()

    r = await client.get(f"/api/share/{share.token}/download")
    assert r.status_code == 200, r.text
    # The response is streaming; the body is bytes (usually a zip for a
    # collection, plain md for single, zip for html_bundle).
    assert len(r.content) > 0


async def _create_public_share_for(client, session, owner, asset) -> str:
    """Owner creates a public share for the given asset, returns the share token."""
    await _login(client, owner)
    r = await client.post(
        f"/api/assets/{asset.id}/shares",
        json={"mode": "public"},
    )
    assert r.status_code == 201
    token = r.json()["token"]
    await client.post("/api/auth/logout")
    return token


@pytest.mark.asyncio
async def test_share_download_md_single_streams_md(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    await session.commit()
    await put_blob(asset, "doc.md", b"# Share me\n")

    share_token = await _create_public_share_for(client, session, owner, asset)

    r = await client.get(f"/api/share/{share_token}/download")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.text == "# Share me\n"


@pytest.mark.asyncio
async def test_share_file_renders_collection_md(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="README.md")
    await session.commit()
    await put_blob(asset, "README.md", b"# R\n")
    await put_blob(asset, "subpage.md", b"## Sub\n")

    share_token = await _create_public_share_for(client, session, owner, asset)

    r = await client.get(
        f"/api/share/{share_token}/file",
        params={"path": "subpage.md"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "subpage.md"
    assert "<h2>" in body["html"]


@pytest.mark.asyncio
async def test_share_file_rejects_md_single(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="d.md")
    await session.commit()
    await put_blob(asset, "d.md", b"# x\n")
    share_token = await _create_public_share_for(client, session, owner, asset)

    r = await client.get(
        f"/api/share/{share_token}/file",
        params={"path": "d.md"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_share_graph_returns_nodes_edges(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="README.md")
    await session.commit()
    await put_blob(asset, "README.md", b"See [[notes]] for more.\n")
    await put_blob(asset, "notes.md", b"# Notes\n")

    share_token = await _create_public_share_for(client, session, owner, asset)

    r = await client.get(f"/api/share/{share_token}/graph")
    assert r.status_code == 200
    body = r.json()
    assert "nodes" in body
    assert "edges" in body


@pytest.mark.asyncio
async def test_share_graph_rejects_md_single(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="d.md")
    await session.commit()
    await put_blob(asset, "d.md", b"# x\n")
    share_token = await _create_public_share_for(client, session, owner, asset)

    r = await client.get(f"/api/share/{share_token}/graph")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_share_html_grant_returns_url(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="html_bundle", entry_path="index.html")
    await session.commit()
    await put_blob(asset, "index.html", b"<html></html>")
    share_token = await _create_public_share_for(client, session, owner, asset)

    r = await client.get(f"/api/share/{share_token}/html-grant")
    assert r.status_code == 200
    assert "_/grant?t=" in r.json()["url"]


@pytest.mark.asyncio
async def test_share_html_grant_rejects_md_kind(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="d.md")
    await session.commit()
    await put_blob(asset, "d.md", b"x\n")
    share_token = await _create_public_share_for(client, session, owner, asset)

    r = await client.get(f"/api/share/{share_token}/html-grant")
    assert r.status_code == 400
