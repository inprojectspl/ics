"""Read-only preview of archived versions.

Key invariant of the feature: `?version=N` never changes asset state.
Promoting old content has exactly one path: `POST /versions/{n}/restore`.
The tests below guard exactly that, plus that entry/tree are computed from
the tree of that version, not from the current asset row.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.models import AssetVersion, ShareLink
from app.slug import generate_token
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user, put_blob


async def _versioned_md(session, owner, *, kind: str = "md_single"):
    """Asset with v1 and v2 in storage; the asset row points at v2."""
    asset = await mk_asset(session, owner, kind=kind, entry_path="doc.md")
    await put_blob(asset, "doc.md", b"# First version\n")
    asset.version = 2
    session.add_all(
        [
            AssetVersion(
                asset_id=asset.id,
                version=1,
                storage_prefix=f"{asset.storage_prefix}/v1",
                size_bytes=18,
                created_by=owner.id,
                created_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
            ),
            AssetVersion(
                asset_id=asset.id,
                version=2,
                storage_prefix=f"{asset.storage_prefix}/v2",
                size_bytes=18,
                created_by=owner.id,
                created_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC),
            ),
        ]
    )
    await session.commit()
    await put_blob(asset, "doc.md", b"# Second version\n")
    return asset


async def _renamed_entry_collection(session, owner):
    """Collection whose entry file changed between versions: v1 has only
    `old/start.md`, v2 adds `README.md` (which becomes the entry).
    The sharpest case for this feature: `asset.entry_path` does not describe v1."""
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="README.md")
    await put_blob(asset, "old/start.md", b"# Old entry point\n")
    asset.version = 2
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=1,
            storage_prefix=f"{asset.storage_prefix}/v1",
            size_bytes=10,
            created_by=owner.id,
        )
    )
    await session.commit()
    await put_blob(asset, "README.md", b"# New readme\n")
    await put_blob(asset, "old/start.md", b"# Old entry point v2\n")
    return asset


@pytest.mark.asyncio
async def test_doc_without_version_returns_current(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _versioned_md(session, owner)
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200
    body = r.json()
    assert "Second version" in body["html"]
    # The current version is not "stale", otherwise the UI would draw a red
    # banner over the current content.
    assert body["preview_version"] is None
    assert body["current_version"] == 2


@pytest.mark.asyncio
async def test_doc_with_version_returns_archived_content(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _versioned_md(session, owner)
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc?version=1")
    assert r.status_code == 200
    body = r.json()
    assert "First version" in body["html"]
    assert body["preview_version"] == 1
    assert body["current_version"] == 2
    assert body["version"] == 1
    assert body["version_created_at"].startswith("2026-01-01")


@pytest.mark.asyncio
async def test_preview_does_not_mutate_asset(client, session, fs_storage):
    """Preview is not restore: no version bump and no new rows."""
    owner = await mk_user(session)
    asset = await _versioned_md(session, owner)
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc?version=1")
    assert r.status_code == 200

    await session.refresh(asset)
    assert asset.version == 2
    assert asset.entry_path == "doc.md"
    count = (
        await session.execute(
            select(func.count()).select_from(AssetVersion).where(AssetVersion.asset_id == asset.id)
        )
    ).scalar_one()
    assert count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, 3, 99])
async def test_doc_rejects_version_out_of_range(client, session, fs_storage, bad):
    owner = await mk_user(session)
    asset = await _versioned_md(session, owner)
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc?version={bad}")
    # 0 fails Query(ge=1) validation -> 422; a real "no such version" -> 404.
    # Both are refusals, neither returns content.
    assert r.status_code in (404, 422)


@pytest.mark.asyncio
async def test_collection_entry_derived_from_that_version(client, session, fs_storage):
    """Entry must not come from `asset.entry_path`: that file did not exist in v1.

    v1: `old/start.md`; v2: `README.md` + `old/start.md`.
    """
    owner = await mk_user(session)
    asset = await _renamed_entry_collection(session, owner)
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc?version=1")
    assert r.status_code == 200
    body = r.json()
    assert body["entry_path"] == "old/start.md"
    assert body["tree"] == ["old/start.md"]
    assert "Old entry point" in body["html"]
    assert "v2" not in body["html"]


@pytest.mark.asyncio
async def test_collection_file_reads_from_version(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="README.md")
    await put_blob(asset, "page.md", b"old page\n")
    asset.version = 2
    await session.commit()
    await put_blob(asset, "page.md", b"new page\n")
    await _login(client, owner)

    r_old = await client.get(f"/api/assets/by-slug/{asset.slug}/file?path=page.md&version=1")
    assert r_old.status_code == 200
    assert "old page" in r_old.json()["html"]
    assert r_old.json()["version"] == 1

    r_new = await client.get(f"/api/assets/by-slug/{asset.slug}/file?path=page.md")
    assert "new page" in r_new.json()["html"]


@pytest.mark.asyncio
async def test_collection_file_missing_in_version_is_404(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="README.md")
    asset.version = 2
    await session.commit()
    await put_blob(asset, "README.md", b"# only v2\n")
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file?path=README.md&version=1")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_share_doc_preview_does_not_burn_views(client, session, fs_storage):
    """`max_views` counts views of the current content. Browsing history must
    not exhaust the limit, otherwise a "single-open link" would die on the
    first click on an archived version."""
    owner = await mk_user(session)
    asset = await _versioned_md(session, owner)
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="public",
        created_by=owner.id,
        max_views=5,
    )
    session.add(share)
    await session.commit()
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{share.token}/doc?version=1")
    assert r.status_code == 200
    assert "First version" in r.json()["html"]
    await session.refresh(share)
    assert share.view_count == 0

    r_cur = await client.get(f"/api/share/{share.token}/doc")
    assert r_cur.status_code == 200
    await session.refresh(share)
    assert share.view_count == 1


@pytest.mark.asyncio
async def test_share_preview_respects_mode_gate(client, session, fs_storage):
    """Version preview does not bypass the link mode gate."""
    owner = await mk_user(session)
    asset = await _versioned_md(session, owner)
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="password",
        created_by=owner.id,
        password_hash="$2b$12$notarealhash",
    )
    session.add(share)
    await session.commit()
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{share.token}/doc?version=1")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_share_file_reads_from_version(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="README.md")
    await put_blob(asset, "page.md", b"old content\n")
    asset.version = 2
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="public",
        created_by=owner.id,
    )
    session.add(share)
    await session.commit()
    await put_blob(asset, "page.md", b"new content\n")
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{share.token}/file?path=page.md&version=1")
    assert r.status_code == 200
    assert "old content" in r.json()["html"]


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["file-mcp", "source"])
async def test_mcp_read_surfaces_serve_archived_version(client, session, fs_storage, endpoint):
    """`file-mcp` and `source` are two surfaces of the same read: both must
    return the requested version's content and report which version they returned."""
    owner = await mk_user(session)
    asset = await _versioned_md(session, owner)
    await _login(client, owner)

    r_old = await client.get(f"/api/assets/by-slug/{asset.slug}/{endpoint}?version=1")
    assert r_old.status_code == 200
    body = r_old.json()
    assert "First version" in body["content"]
    assert (body["version"], body["current_version"]) == (1, 2)

    r_cur = await client.get(f"/api/assets/by-slug/{asset.slug}/{endpoint}")
    assert "Second version" in r_cur.json()["content"]
    assert r_cur.json()["version"] == 2


@pytest.mark.asyncio
async def test_file_mcp_entry_comes_from_that_version(client, session, fs_storage):
    """Without `path` the entry file must come from the tree of the version
    being read: `README.md` did not exist yet in v1."""
    owner = await mk_user(session)
    asset = await _renamed_entry_collection(session, owner)
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?version=1")
    assert r.status_code == 200
    assert r.json()["path"] == "old/start.md"
    assert "Old entry point" in r.json()["content"]


@pytest.mark.asyncio
async def test_file_mcp_rejects_version_out_of_range(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _versioned_md(session, owner)
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?version=99")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_files_mcp_lists_archived_inventory(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _renamed_entry_collection(session, owner)
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/files-mcp?version=1")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1
    assert [f["path"] for f in body["files"]] == ["old/start.md"]
    assert body["entry_path"] == "old/start.md"

    r_cur = await client.get(f"/api/assets/by-slug/{asset.slug}/files-mcp")
    assert [f["path"] for f in r_cur.json()["files"]] == ["README.md", "old/start.md"]
    assert r_cur.json()["entry_path"] == "README.md"


@pytest.mark.asyncio
async def test_mcp_version_read_does_not_mutate_asset(client, session, fs_storage):
    """Same invariant as for the UI: reading an archive promotes nothing."""
    owner = await mk_user(session)
    asset = await _versioned_md(session, owner)
    await _login(client, owner)

    for path in ("file-mcp?version=1", "files-mcp?version=1", "source?version=1"):
        assert (await client.get(f"/api/assets/by-slug/{asset.slug}/{path}")).status_code == 200

    await session.refresh(asset)
    assert asset.version == 2
    assert asset.entry_path == "doc.md"
