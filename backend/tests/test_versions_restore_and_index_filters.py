"""Branches of `assets/versions.py` (restore + create_version)
and `mcp_assets/index.py` (shared_with_me/owned/tag/q/updated_since filters).
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pytest

from app.models import AssetPin, AssetShare, AssetVersion
from app.slug import generate_slug
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user, put_blob


async def _setup_with_history(client, session) -> tuple:
    """Asset with 2 versions in storage + 2 AssetVersion rows."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await session.commit()

    # v1
    await put_blob(asset, "doc.md", b"v1 content\n", versioned=True)
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=1,
            storage_prefix=f"{asset.storage_prefix}/v1",
            size_bytes=11,
        )
    )

    # Bump asset to v2
    asset.version = 2
    await put_blob(asset, "doc.md", b"v2 content - newer\n", versioned=True)
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=2,
            storage_prefix=f"{asset.storage_prefix}/v2",
            size_bytes=19,
        )
    )
    asset.size_bytes = 19
    await session.commit()
    await _login(client, user)
    return user, asset


@pytest.mark.asyncio
async def test_restore_version_creates_v_plus_one(client, session, fs_storage):
    _user, asset = await _setup_with_history(client, session)

    r = await client.post(f"/api/assets/{asset.id}/versions/1/restore")
    assert r.status_code == 201
    body = r.json()
    assert body["version"] == 3

    # Asset bumped to v3 with content from v1
    await session.refresh(asset)
    assert asset.version == 3


@pytest.mark.asyncio
async def test_restore_same_version_returns_400(client, session, fs_storage):
    _user, asset = await _setup_with_history(client, session)
    r = await client.post(f"/api/assets/{asset.id}/versions/2/restore")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_restore_version_zero_returns_400(client, session, fs_storage):
    _user, asset = await _setup_with_history(client, session)
    r = await client.post(f"/api/assets/{asset.id}/versions/0/restore")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_restore_future_version_returns_400(client, session, fs_storage):
    """A version greater than current cannot be restored."""
    _user, asset = await _setup_with_history(client, session)
    r = await client.post(f"/api/assets/{asset.id}/versions/99/restore")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_restore_nonexistent_version_returns_404(client, session, fs_storage):
    """Asset has current v=5 but no AssetVersion row for v=2."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    asset.version = 5
    await session.commit()
    await put_blob(asset, "doc.md", b"v5\n", versioned=True)
    await _login(client, user)

    # No AssetVersion row for v3: 404
    r = await client.post(f"/api/assets/{asset.id}/versions/3/restore")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_version_md_single_with_one_md(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="orig.md")
    await session.commit()
    await put_blob(asset, "orig.md", b"v1\n", versioned=True)
    await _login(client, user)

    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files={"files": ("new.md", b"updated content\n", "text/markdown")},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["version"] == 2
    assert body["entry_path"] == "new.md"
    assert body["file_count"] == 1


@pytest.mark.asyncio
async def test_create_version_md_single_rejects_multiple_files(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="d.md")
    await session.commit()
    await put_blob(asset, "d.md", b"v1\n", versioned=True)
    await _login(client, user)

    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files=[
            ("files", ("a.md", b"a\n", "text/markdown")),
            ("files", ("b.md", b"b\n", "text/markdown")),
        ],
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_version_md_single_rejects_non_md(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="d.md")
    await session.commit()
    await put_blob(asset, "d.md", b"v1\n", versioned=True)
    await _login(client, user)

    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files={"files": ("d.txt", b"text\n", "text/plain")},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_version_empty_files_returns_400(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="d.md")
    await session.commit()
    await _login(client, user)

    r = await client.post(f"/api/assets/{asset.id}/versions", files=[])
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_create_version_md_collection_with_paths(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_collection", entry_path="README.md")
    await session.commit()
    await put_blob(asset, "README.md", b"# r\n", versioned=True)
    await _login(client, user)

    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files=[
            ("files", ("ignored1", io.BytesIO(b"# r2\n"), "text/markdown")),
            ("files", ("ignored2", io.BytesIO(b"# n\n"), "text/markdown")),
        ],
        data={"paths": ["README.md", "new.md"]},
    )
    assert r.status_code == 201
    assert r.json()["file_count"] == 2


@pytest.mark.asyncio
async def test_create_version_collection_mismatched_paths_returns_400(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_collection", entry_path="r.md")
    await session.commit()
    await _login(client, user)

    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files=[("files", ("a", io.BytesIO(b"a\n"), "text/markdown"))],
        data={"paths": ["a.md", "b.md"]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_create_version_html_bundle_with_index(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle", entry_path="index.html")
    await session.commit()
    await _login(client, user)

    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files=[
            ("files", ("ign1", io.BytesIO(b"<html></html>"), "text/html")),
            ("files", ("ign2", io.BytesIO(b"body{}"), "text/css")),
        ],
        data={"paths": ["index.html", "style.css"]},
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_create_version_collection_without_md_returns_400(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_collection", entry_path="r.md")
    await session.commit()
    await _login(client, user)

    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files=[("files", ("any", io.BytesIO(b"data\n"), "text/plain"))],
        data={"paths": ["data.txt"]},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_index_filter_shared_with_me(client, session):
    """`shared_with_me=true` returns only active shares, not owned assets."""
    owner = await mk_user(session)
    viewer = await mk_user(session)
    await mk_asset(session, viewer, title="MyAsset")  # owned by viewer
    shared = await mk_asset(session, owner, title="SharedAsset")
    await session.commit()
    session.add(AssetShare(asset_id=shared.id, user_id=viewer.id, role="viewer"))
    await session.commit()
    await _login(client, viewer)

    r = await client.get("/api/assets/index", params={"shared_with_me": "true"})
    assert r.status_code == 200
    body = r.json()
    titles = {item["title"] for item in body["items"]}
    assert "SharedAsset" in titles
    assert "MyAsset" not in titles


@pytest.mark.asyncio
async def test_index_filter_owned_false(client, session):
    """`owned=false`: same as shared_with_me."""
    owner = await mk_user(session)
    viewer = await mk_user(session)
    await mk_asset(session, viewer, title="O1")
    shared = await mk_asset(session, owner, title="S1")
    await session.commit()
    session.add(AssetShare(asset_id=shared.id, user_id=viewer.id, role="viewer"))
    await session.commit()
    await _login(client, viewer)

    r = await client.get("/api/assets/index", params={"owned": "false"})
    assert r.status_code == 200
    titles = {it["title"] for it in r.json()["items"]}
    assert "S1" in titles
    assert "O1" not in titles


@pytest.mark.asyncio
async def test_index_filter_by_tag(client, session):
    """`tags @> ARRAY[...]`: the `?tag=urgent` filter returns only assets that
    have the tag."""
    user = await mk_user(session)
    tagged = await mk_asset(session, user, title="Tagged")
    await mk_asset(session, user, title="Plain")
    tagged.tags = ["urgent", "internal"]
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/index", params={"tag": "urgent"})
    assert r.status_code == 200
    titles = {it["title"] for it in r.json()["items"]}
    assert "Tagged" in titles
    assert "Plain" not in titles


@pytest.mark.asyncio
async def test_index_filter_by_multiple_tags_requires_all(client, session):
    """`tag` query repeated -> AND (`tags @> ARRAY[t1, t2]`)."""
    user = await mk_user(session)
    both = await mk_asset(session, user, title="Both")
    only_one = await mk_asset(session, user, title="OnlyOne")
    both.tags = ["a", "b"]
    only_one.tags = ["a"]
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/index?tag=a&tag=b")
    assert r.status_code == 200
    titles = {it["title"] for it in r.json()["items"]}
    assert "Both" in titles
    assert "OnlyOne" not in titles


@pytest.mark.asyncio
async def test_index_filter_by_q_substring(client, session):
    user = await mk_user(session)
    await mk_asset(session, user, title="Quarterly Report")
    await mk_asset(session, user, title="Random Note")
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/index", params={"q": "quarter"})
    assert r.status_code == 200
    titles = {it["title"] for it in r.json()["items"]}
    assert "Quarterly Report" in titles
    assert "Random Note" not in titles


@pytest.mark.asyncio
async def test_index_filter_updated_since(client, session):
    user = await mk_user(session)
    await mk_asset(session, user, title="Fresh")
    await session.commit()
    await _login(client, user)

    # Everything has updated_at = now +/- delta. A filter in the past returns everything.
    past = (datetime.now(UTC) - timedelta(days=365)).isoformat()
    r = await client.get("/api/assets/index", params={"updated_since": past})
    assert r.status_code == 200
    assert any(it["title"] == "Fresh" for it in r.json()["items"])

    # A filter in the future returns nothing.
    future = (datetime.now(UTC) + timedelta(days=365)).isoformat()
    r2 = await client.get("/api/assets/index", params={"updated_since": future})
    assert r2.status_code == 200
    assert r2.json()["items"] == []


@pytest.mark.asyncio
async def test_index_returns_ndjson_when_accept_ndjson(client, session):
    user = await mk_user(session)
    await mk_asset(session, user, title="Single")
    await session.commit()
    await _login(client, user)

    r = await client.get(
        "/api/assets/index",
        headers={"Accept": "application/x-ndjson"},
    )
    assert r.status_code == 200
    assert "application/x-ndjson" in r.headers["content-type"]
    # NDJSON: each line is a separate JSON document.
    lines = [line for line in r.text.strip().split("\n") if line]
    assert lines  # at least 1


@pytest.mark.asyncio
async def test_index_pinned_filter(client, session):
    user = await mk_user(session)
    pinned = await mk_asset(session, user, title="Pinned")
    await mk_asset(session, user, title="Floating")
    session.add(AssetPin(user_id=user.id, asset_id=pinned.id, pinned_at=datetime.now(UTC)))
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/index", params={"pinned": "true"})
    titles = {it["title"] for it in r.json()["items"]}
    assert "Pinned" in titles
    assert "Floating" not in titles

    r2 = await client.get("/api/assets/index", params={"pinned": "false"})
    titles2 = {it["title"] for it in r2.json()["items"]}
    assert "Floating" in titles2
    assert "Pinned" not in titles2


@pytest.mark.asyncio
async def test_index_project_id_filter(client, session):
    from app.models import Project

    user = await mk_user(session)
    proj = Project(name="Test Project", slug=generate_slug(), created_by=user.id)
    session.add(proj)
    await session.flush()
    in_proj = await mk_asset(session, user, title="ProjFile")
    in_proj.project_id = proj.id
    await mk_asset(session, user, title="Standalone")
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/index", params={"project_id": str(proj.id)})
    assert r.status_code == 200
    titles = {it["title"] for it in r.json()["items"]}
    assert "ProjFile" in titles
    assert "Standalone" not in titles
