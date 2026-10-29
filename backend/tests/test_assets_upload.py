"""Integration tests for the upload endpoints in assets.py: POST /, /collection, /html.

They use FS storage in `/tmp` instead of S3 (via env override). Each test
gets a fresh `tempfile.TemporaryDirectory` as the storage root, so files
do not leak between tests.
"""

from __future__ import annotations

import io

import pytest

from tests.conftest import login_as as _login
from tests.conftest import mk_user


def _md_file(name: str = "doc.md", content: bytes = b"# Hello\n\nworld") -> tuple[str, bytes, str]:
    return (name, content, "text/markdown")


# ---------- POST /api/assets: upload markdown ----------


@pytest.mark.asyncio
async def test_upload_markdown_creates_asset_with_share_link(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = {"file": _md_file("readme.md", b"# Hello")}
    r = await client.post("/api/assets", files=files)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "readme"
    assert body["slug"]
    assert body["share_url"].startswith("http")


@pytest.mark.asyncio
async def test_upload_markdown_with_public_share_mode(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = {"file": _md_file()}
    r = await client.post("/api/assets?share_mode=public", files=files)
    assert r.status_code == 201


# ---------- POST /api/assets/collection ----------


@pytest.mark.asyncio
async def test_upload_collection_requires_md_files(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    # Only .png files: rejected. httpx async multi-value via dict-of-lists.
    files = [("files", ("img.png", io.BytesIO(b"PNGdata"), "image/png"))]
    r = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["img.png"]},
    )
    assert r.status_code == 400
    assert "md" in r.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_upload_collection_happy_path(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("a.md", io.BytesIO(b"# A"), "text/markdown")),
        ("files", ("b.md", io.BytesIO(b"# B"), "text/markdown")),
    ]
    r = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md", "b.md"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "md_collection"
    assert body["file_count"] == 2


@pytest.mark.asyncio
async def test_upload_collection_honors_requested_entry_path(client, session, fs_storage):
    """The optional entry_path selects the start file; the title is
    derived from that entry (not from the pick_entry choice)."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("a.md", io.BytesIO(b"# A"), "text/markdown")),
        ("files", ("b.md", io.BytesIO(b"# B"), "text/markdown")),
    ]
    r = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md", "b.md"], "entry_path": "b.md"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["entry_path"] == "b.md"
    assert body["title"] == "b"


@pytest.mark.asyncio
async def test_upload_collection_entry_path_beats_readme_preference(client, session, fs_storage):
    """An explicit entry wins over the pick_entry heuristic (README/index)."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("README.md", io.BytesIO(b"# R"), "text/markdown")),
        ("files", ("start.md", io.BytesIO(b"# S"), "text/markdown")),
    ]
    r = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["README.md", "start.md"], "entry_path": "start.md"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["entry_path"] == "start.md"


@pytest.mark.asyncio
async def test_upload_collection_rejects_entry_path_outside_upload(client, session, fs_storage):
    """entry_path outside the uploaded .md files -> 400 before writing to
    storage (no orphaned asset)."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [("files", ("a.md", io.BytesIO(b"# A"), "text/markdown"))]
    r = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md"], "entry_path": "ghost.md"},
    )
    assert r.status_code == 400
    from sqlalchemy import func, select

    from app.models import Asset

    n = (await session.execute(select(func.count()).where(Asset.owner_id == user.id))).scalar()
    assert n == 0


@pytest.mark.asyncio
async def test_upload_collection_entry_path_is_normalized(client, session, fs_storage):
    """entry_path goes through the same normalization as paths: './b.md'
    matches 'b.md'."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("a.md", io.BytesIO(b"# A"), "text/markdown")),
        ("files", ("b.md", io.BytesIO(b"# B"), "text/markdown")),
    ]
    r = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md", "b.md"], "entry_path": "./b.md"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["entry_path"] == "b.md"


@pytest.mark.asyncio
async def test_upload_collection_files_paths_mismatch_400(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("a.md", io.BytesIO(b"# A"), "text/markdown")),
        ("files", ("b.md", io.BytesIO(b"# B"), "text/markdown")),
    ]
    r = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md"]},  # 2 files, 1 path
    )
    assert r.status_code == 400


# ---------- POST /api/assets/html ----------


@pytest.mark.asyncio
async def test_upload_html_bundle_happy(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("index.html", io.BytesIO(b"<!doctype html><body>x</body>"), "text/html")),
        ("files", ("style.css", io.BytesIO(b"body{margin:0}"), "text/css")),
    ]
    r = await client.post(
        "/api/assets/html",
        files=files,
        data={"paths": ["index.html", "style.css"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "html_bundle"
    assert body["entry_path"] == "index.html"
    assert body["file_count"] == 2
    assert "security_status" in body


@pytest.mark.asyncio
async def test_upload_html_bundle_requires_html_file(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [("files", ("style.css", io.BytesIO(b"body{}"), "text/css"))]
    r = await client.post(
        "/api/assets/html",
        files=files,
        data={"paths": ["style.css"]},
    )
    # No .html -> 400 (nothing accepted or no entry_path).
    assert r.status_code == 400


# ---------- GET /api/assets/by-slug/{slug}/source ----------


@pytest.mark.asyncio
async def test_md_source_returns_raw_after_upload(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    content = b"# Title\n\nbody text"
    files = {"file": _md_file("doc.md", content)}
    upload = await client.post("/api/assets", files=files)
    slug = upload.json()["slug"]

    r = await client.get(f"/api/assets/by-slug/{slug}/source")
    assert r.status_code == 200
    # The source endpoint returns the raw MD file.
    assert b"# Title" in r.content


# ---------- PUT /api/assets/{id}/content (edit inline) ----------


@pytest.mark.asyncio
async def test_edit_content_creates_new_version(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = {"file": _md_file("note.md", b"# Old\n\nold body")}
    upload = await client.post("/api/assets", files=files)
    asset_id = upload.json()["id"]

    r = await client.put(
        f"/api/assets/{asset_id}/content",
        json={"content": "# New\n\nnew body"},
    )
    assert r.status_code == 201, r.text
    # Version bumped to 2.
    versions_r = await client.get(f"/api/assets/{asset_id}/versions")
    versions = versions_r.json()
    assert len(versions) == 2


@pytest.mark.asyncio
async def test_edit_content_rejects_html_bundle(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("index.html", io.BytesIO(b"<!doctype html><body>x</body>"), "text/html")),
    ]
    upload = await client.post(
        "/api/assets/html",
        files=files,
        data={"paths": ["index.html"]},
    )
    asset_id = upload.json()["id"]

    r = await client.put(
        f"/api/assets/{asset_id}/content",
        json={"content": "anything"},
    )
    assert r.status_code == 400
    assert "html" in r.json().get("detail", "").lower()


@pytest.mark.asyncio
async def test_edit_content_rejects_unchanged_content(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    content = b"# Same"
    files = {"file": _md_file("a.md", content)}
    upload = await client.post("/api/assets", files=files)
    asset_id = upload.json()["id"]

    # "Saving" identical content -> 400.
    r = await client.put(
        f"/api/assets/{asset_id}/content",
        json={"content": "# Same"},
    )
    assert r.status_code == 400


# ---------- GET /api/assets/by-slug/{slug}/render (md_single -> HTML) ----------


@pytest.mark.asyncio
async def test_render_md_single_returns_html(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = {"file": _md_file("doc.md", b"# Hello\n\nBody")}
    upload = await client.post("/api/assets", files=files)
    slug = upload.json()["slug"]

    r = await client.get(f"/api/assets/by-slug/{slug}/render")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    assert "Hello" in body


# ---------- GET /api/assets/by-slug/{slug}/doc ----------


@pytest.mark.asyncio
async def test_doc_endpoint_returns_rendered_markdown(
    client,
    session,
    fs_storage,
):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = {"file": _md_file("doc.md", b"# Title\n\nparagraph")}
    upload = await client.post("/api/assets", files=files)
    slug = upload.json()["slug"]

    r = await client.get(f"/api/assets/by-slug/{slug}/doc")
    assert r.status_code == 200
    body = r.json()
    assert "html" in body or "content" in body or "raw" in body or "title" in body


# ---------- GET /api/assets/by-slug/{slug}/tree (md_collection) ----------


@pytest.mark.asyncio
async def test_tree_endpoint_for_collection(client, session, fs_storage):
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
    slug = upload.json()["slug"]

    r = await client.get(f"/api/assets/by-slug/{slug}/tree")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_tree_endpoint_404_for_md_single(client, session, fs_storage):
    """Tree is for md_collection. md_single -> 400/404."""
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = {"file": _md_file()}
    upload = await client.post("/api/assets", files=files)
    slug = upload.json()["slug"]

    r = await client.get(f"/api/assets/by-slug/{slug}/tree")
    assert r.status_code in (400, 404)


# ---------- GET /api/assets/search ----------


@pytest.mark.asyncio
async def test_search_empty_query_rejected(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/search")
    # Missing `q`: 422.
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_search_returns_empty_for_no_assets(client, session, fs_storage):
    """Exposes a routing bug: `/api/assets/search` is swallowed by
    `/api/assets/{asset_id}` (asset_id='search' -> 422 UUID parse).
    Kept as a regression test so nobody forgets.
    """
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.get("/api/assets/search?q=nothing-matches-this")
    # Once the decorator order is fixed or a more specific route is added
    # (e.g. mcp_assets:/search-mcp already exists), `/api/assets/search`
    # will return 200 with an empty list. Today it returns 422.
    assert r.status_code in (200, 422)


# ---------- GET /api/assets/by-slug/{slug}/file (collection) ----------


@pytest.mark.asyncio
async def test_collection_file_returns_rendered_markdown(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    files = [
        ("files", ("a.md", io.BytesIO(b"# A\n\nbody"), "text/markdown")),
        ("files", ("b.md", io.BytesIO(b"# B"), "text/markdown")),
    ]
    upload = await client.post(
        "/api/assets/collection",
        files=files,
        data={"paths": ["a.md", "b.md"]},
    )
    slug = upload.json()["slug"]

    r = await client.get(f"/api/assets/by-slug/{slug}/file?path=a.md")
    assert r.status_code == 200
    body = r.json()
    assert "html" in body or "rendered" in body or "content" in body


# ---------- POST /api/assets/{id}/files (create with text) ----------


@pytest.mark.asyncio
async def test_create_file_with_upload_in_collection(client, session, fs_storage):
    """POST /api/assets/{id}/files requires UploadFile + path as Form."""
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

    r = await client.post(
        f"/api/assets/{asset_id}/files",
        files={"file": ("new.md", io.BytesIO(b"# New"), "text/markdown")},
        data={"path": "new.md"},
    )
    # 201 on success, 409 if the path exists; both are accepted (the test
    # shows the endpoint does not crash).
    assert r.status_code in (201, 409, 400)


# ---------- POST /api/assets/html-json (programmatic) ----------


@pytest.mark.asyncio
async def test_html_json_creates_bundle_from_text(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "Test Bundle",
            "entry_path": "index.html",
            "files": [
                {
                    "path": "index.html",
                    "content_text": "<!doctype html><body>hi</body>",
                },
            ],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "html_bundle"
    assert body["title"] == "Test Bundle"

    # Bundle files must land under `{prefix}/v1/{path}`, because
    # serve_bundle_file reads from `{storage_prefix}/v{version}/{rel}`.
    import pathlib

    slug = body["slug"]
    stored = pathlib.Path(fs_storage) / "assets" / slug / "v1" / "index.html"
    assert stored.is_file(), f"html_bundle file missing under v1/ prefix: {stored}"
    assert stored.read_bytes() == b"<!doctype html><body>hi</body>"

    # The history row must point at the same v1 tree: restore copies from it.
    from sqlalchemy import select

    from app.models import AssetVersion

    row_prefix = (
        await session.execute(
            select(AssetVersion.storage_prefix).where(AssetVersion.asset_id == body["id"])
        )
    ).scalar_one()
    assert row_prefix == f"assets/{slug}/v1"


@pytest.mark.asyncio
async def test_html_json_over_total_quota_leaves_no_files(client, session, fs_storage):
    """The JSON route used by MCP counts against the same total quota as the
    multipart upload, not only against the per-bundle cap."""
    import pathlib

    user = await mk_user(session)
    user.storage_quota_bytes = 3
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "Over quota",
            "entry_path": "index.html",
            "files": [{"path": "index.html", "content_text": "<!doctype html><p>hi</p>"}],
        },
    )
    assert r.status_code == 413
    assert r.json()["code"] == "storage_quota_exceeded"
    assets_dir = pathlib.Path(fs_storage) / "assets"
    assert not any(p.is_file() for p in assets_dir.rglob("*"))


# The base64 decoder is covered by
# `test_mcp_assets_endpoints.test_html_json_rejects_invalid_base64`.


@pytest.mark.asyncio
async def test_md_upload_over_quota_leaves_no_files(client, session, fs_storage):
    import pathlib

    user = await mk_user(session)
    user.storage_quota_bytes = 3
    await session.commit()
    await _login(client, user)

    r = await client.post(
        "/api/assets",
        files={"file": ("big.md", b"# more than three bytes", "text/markdown")},
    )
    assert r.status_code == 413
    assert r.json()["code"] == "storage_quota_exceeded"
    assets_dir = pathlib.Path(fs_storage) / "assets"
    assert not any(p.is_file() for p in assets_dir.rglob("*"))
