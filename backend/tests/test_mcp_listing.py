"""Tests for `mcp_assets/listing.py` (`/by-slug/{slug}/files-mcp`)."""

from __future__ import annotations

import pytest

from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_html_bundle, mk_user, put_blob


@pytest.mark.asyncio
async def test_files_mcp_lists_bundle_files_with_sizes(client, session, fs_storage):
    files = {
        "index.html": b"<html><body>hi</body></html>",
        "assets/style.css": b"body{}",
        "img/logo.png": b"\x89PNG\r\n\x1a\n\x00\xff",
    }
    _, asset = await mk_html_bundle(client, session, files)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/files-mcp")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == asset.slug
    assert body["kind"] == "html_bundle"
    assert body["version"] == asset.version
    assert body["entry_path"] == "index.html"
    assert body["files"] == [
        {"path": "assets/style.css", "size_bytes": len(files["assets/style.css"])},
        {"path": "img/logo.png", "size_bytes": len(files["img/logo.png"])},
        {"path": "index.html", "size_bytes": len(files["index.html"])},
    ]


@pytest.mark.asyncio
async def test_files_mcp_lists_md_collection(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_collection", entry_path="index.md")
    await session.commit()
    await put_blob(asset, "index.md", b"# home")
    await put_blob(asset, "notes/a.md", b"# a")
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/files-mcp")
    assert r.status_code == 200
    body = r.json()
    assert [f["path"] for f in body["files"]] == ["index.md", "notes/a.md"]


@pytest.mark.asyncio
async def test_files_mcp_md_single_returns_one_file(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await session.commit()
    await put_blob(asset, "doc.md", b"# doc")
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/files-mcp")
    assert r.status_code == 200
    body = r.json()
    assert [f["path"] for f in body["files"]] == ["doc.md"]


@pytest.mark.asyncio
async def test_files_mcp_unknown_kind_rejected(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="mystery_kind")
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/files-mcp")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_files_mcp_missing_asset_404(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/by-slug/no-such-slug/files-mcp")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_files_mcp_requires_auth(client, session, fs_storage):
    _, asset = await mk_html_bundle(client, session, {"index.html": b"<html></html>"})
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/files-mcp")
    assert r.status_code == 401
