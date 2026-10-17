"""Tests for the `routes/assets.py` versions endpoints: list + diff + 400/404 paths.

Covers validation (version range, identical versions, html_bundle diff).
The full diff flow (different contents in storage) is out of scope; it is a
separate integration test in `_e2e_golden_path.py`.
"""

from __future__ import annotations

import io

import pytest

from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user

# ---------- /diff ----------


@pytest.mark.asyncio
async def test_diff_rejects_same_versions(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.version = 3
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/{asset.id}/versions/1/diff/1")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_diff_rejects_version_out_of_range(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.version = 2
    await session.commit()
    await _login(client, user)

    # Version 99 does not exist.
    r = await client.get(f"/api/assets/{asset.id}/versions/1/diff/99")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_diff_accepts_html_bundle(client, session, fs_storage):
    """A bundle is compared like any other kind (no files in storage here, so the change
    list is empty)."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="html_bundle")
    asset.version = 3
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/{asset.id}/versions/1/diff/2")
    assert r.status_code == 200
    assert r.json()["files"] == []


# ---------- /create_version (POST /api/assets/{id}/versions) ----------


@pytest.mark.asyncio
async def test_create_version_md_single_with_real_upload(
    client,
    session,
    fs_storage,
):
    """Create an MD asset via upload, then POST /versions with new content.
    Version bumps from 1 to 2."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    # 1) Initial upload.
    upload = await client.post(
        "/api/assets",
        files={"file": ("note.md", io.BytesIO(b"# Initial"), "text/markdown")},
    )
    asset_id = upload.json()["id"]

    # 2) Create new version.
    r = await client.post(
        f"/api/assets/{asset_id}/versions",
        files={"files": ("note.md", io.BytesIO(b"# Updated"), "text/markdown")},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["version"] == 2


@pytest.mark.asyncio
async def test_create_version_kind_invariant(client, session, fs_storage):
    """Trying to switch md_single to html_bundle via create_version
    must fail (asset.kind is immutable)."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    upload = await client.post(
        "/api/assets",
        files={"file": ("a.md", io.BytesIO(b"# x"), "text/markdown")},
    )
    asset_id = upload.json()["id"]

    # Sending html as a new md_single version is rejected.
    r = await client.post(
        f"/api/assets/{asset_id}/versions",
        files={"files": ("index.html", io.BytesIO(b"<html></html>"), "text/html")},
    )
    assert r.status_code in (400, 422)


@pytest.mark.asyncio
async def test_create_version_respects_bundle_cap(client, session, fs_storage):
    """Replacing a bundle version is the third door to the same limit: the
    upload passes under the default cap, and once the cap is lowered the new
    version gets 413."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    upload = await client.post(
        "/api/assets/html",
        files=[("files", ("index.html", io.BytesIO(b"<html>v1</html>"), "text/html"))],
        data={"paths": ["index.html"]},
    )
    assert upload.status_code == 201, upload.text
    asset_id = upload.json()["id"]

    user.bundle_max_bytes = 4
    await session.commit()

    r = await client.post(
        f"/api/assets/{asset_id}/versions",
        files=[("files", ("index.html", io.BytesIO(b"<html>v2</html>"), "text/html"))],
        data={"paths": ["index.html"]},
    )
    assert r.status_code == 413, r.text


# ---------- /files (DELETE, POST text, empty file) ----------


@pytest.mark.asyncio
async def test_create_empty_file_in_collection(client, session, fs_storage):
    """After a collection upload, an empty file can be added."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    # Upload a collection.
    files = [
        ("files", ("a.md", io.BytesIO(b"# A"), "text/markdown")),
        ("files", ("b.md", io.BytesIO(b"# B"), "text/markdown")),
    ]
    upload = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md", "b.md"]},
    )
    assert upload.status_code == 201
    asset_id = upload.json()["id"]

    # Empty file.
    r = await client.post(
        f"/api/assets/{asset_id}/files/empty",
        json={"path": "new-page.md"},
    )
    # 201 on success, 409 if the path is taken.
    assert r.status_code in (201, 409)


@pytest.mark.asyncio
async def test_files_endpoints_reject_non_owner(client, session, fs_storage):
    owner = await mk_user(session)
    await session.commit()
    await _login(client, owner)

    upload = await client.post(
        "/api/assets",
        files={"file": ("doc.md", io.BytesIO(b"# x"), "text/markdown")},
    )
    asset_id = upload.json()["id"]
    await client.post("/api/auth/logout")

    stranger = await mk_user(session)
    await session.commit()
    await _login(client, stranger)

    r = await client.post(
        f"/api/assets/{asset_id}/files/empty",
        json={"path": "evil.md"},
    )
    assert r.status_code in (403, 404)


# ---------- DELETE /api/assets/{id}/files ----------


@pytest.mark.asyncio
async def test_delete_file_from_md_single_rejected(client, session, fs_storage):
    """md_single has only 1 file; the files DELETE endpoint works only for collections."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    upload = await client.post(
        "/api/assets",
        files={"file": ("a.md", io.BytesIO(b"# x"), "text/markdown")},
    )
    asset_id = upload.json()["id"]

    r = await client.delete(f"/api/assets/{asset_id}/files?path=a.md")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_delete_file_404_for_unknown_path(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("a.md", io.BytesIO(b"# A"), "text/markdown")),
        ("files", ("b.md", io.BytesIO(b"# B"), "text/markdown")),
    ]
    upload = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md", "b.md"]},
    )
    asset_id = upload.json()["id"]

    r = await client.delete(f"/api/assets/{asset_id}/files?path=nonexistent.md")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_file_404_for_non_md_extension(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("a.md", io.BytesIO(b"# A"), "text/markdown")),
        ("files", ("b.md", io.BytesIO(b"# B"), "text/markdown")),
    ]
    upload = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md", "b.md"]},
    )
    asset_id = upload.json()["id"]

    r = await client.delete(f"/api/assets/{asset_id}/files?path=image.png")
    assert r.status_code == 400
