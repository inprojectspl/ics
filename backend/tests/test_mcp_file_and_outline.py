"""Tests for `mcp_assets/partial_read.py` (`/file-mcp`) and `mcp_assets/outline.py`."""

from __future__ import annotations

import pytest

from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_html_bundle, mk_user, put_blob

# ============================================================
#  /by-slug/{slug}/file-mcp
# ============================================================


@pytest.mark.asyncio
async def test_file_mcp_returns_full_content_for_md_single(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await session.commit()
    await put_blob(asset, "doc.md", b"# Hello\n\nLine 2\nLine 3", versioned=True)
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == asset.slug
    assert body["path"] == "doc.md"
    assert body["content"] == "# Hello\n\nLine 2\nLine 3"
    assert body["total_lines"] == 4
    assert body["returned_range"] == [1, 4]


@pytest.mark.asyncio
async def test_file_mcp_line_range_returns_slice(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await session.commit()
    body_bytes = "\n".join(f"line {i}" for i in range(1, 21)).encode()  # 20 lines
    await put_blob(asset, "doc.md", body_bytes, versioned=True)
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?lines=5-7")
    assert r.status_code == 200
    body = r.json()
    assert body["returned_range"] == [5, 7]
    assert body["content"] == "line 5\nline 6\nline 7"
    assert body["total_lines"] == 20


@pytest.mark.asyncio
async def test_file_mcp_path_traversal_blocked(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_collection", entry_path="index.md")
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?path=../etc/passwd")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_file_mcp_absolute_path_stays_in_prefix(client, session, fs_storage):
    """A leading `/` is stripped by normalize_collection_path (as in
    serve_bundle_file): the path stays relative to the asset prefix, so
    `/etc/passwd` reads at most `{prefix}/etc/passwd` -> 404."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_collection", entry_path="index.md")
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?path=/etc/passwd")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_file_mcp_kind_unknown_rejected(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="mystery_kind")
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp")
    assert r.status_code == 400


# ============================================================
#  /by-slug/{slug}/file-mcp: html_bundle
# ============================================================

_PNG_BYTES = b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe\x01binary"  # invalid UTF-8


@pytest.mark.asyncio
async def test_file_mcp_bundle_defaults_to_entry_path(client, session, fs_storage):
    _, asset = await mk_html_bundle(
        client, session, {"index.html": b"<html>\n<body>hi</body>\n</html>"}
    )

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == "index.html"
    assert body["content"] == "<html>\n<body>hi</body>\n</html>"
    assert body["total_lines"] == 3
    assert body["returned_range"] == [1, 3]


@pytest.mark.asyncio
async def test_file_mcp_bundle_reads_nested_file_by_path(client, session, fs_storage):
    _, asset = await mk_html_bundle(
        client,
        session,
        {"index.html": b"<html></html>", "assets/style.css": b"body { color: red; }"},
    )

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?path=assets/style.css")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["path"] == "assets/style.css"
    assert body["content"] == "body { color: red; }"


@pytest.mark.asyncio
async def test_file_mcp_bundle_line_range(client, session, fs_storage):
    lines = "\n".join(f"<p>line {i}</p>" for i in range(1, 11)).encode()
    _, asset = await mk_html_bundle(client, session, {"index.html": lines})

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?lines=2-3")
    assert r.status_code == 200
    body = r.json()
    assert body["returned_range"] == [2, 3]
    assert body["content"] == "<p>line 2</p>\n<p>line 3</p>"


@pytest.mark.asyncio
async def test_file_mcp_bundle_traversal_blocked(client, session, fs_storage):
    _, asset = await mk_html_bundle(client, session, {"index.html": b"<html></html>"})

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?path=../other/index.html")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_file_mcp_bundle_disallowed_extension_404(client, session, fs_storage):
    _, asset = await mk_html_bundle(client, session, {"index.html": b"<html></html>"})
    await put_blob(asset, "shell.php", b"<?php echo 1; ?>")

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?path=shell.php")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_file_mcp_bundle_missing_file_404(client, session, fs_storage):
    _, asset = await mk_html_bundle(client, session, {"index.html": b"<html></html>"})

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?path=nope.html")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_file_mcp_bundle_binary_without_flag_415(client, session, fs_storage):
    _, asset = await mk_html_bundle(
        client, session, {"index.html": b"<html></html>", "img/logo.png": _PNG_BYTES}
    )

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?path=img/logo.png")
    assert r.status_code == 415
    detail = r.json()["detail"]
    assert detail["mime"] == "image/png"
    assert detail["size_bytes"] == len(_PNG_BYTES)


@pytest.mark.asyncio
async def test_file_mcp_bundle_binary_base64_optin(client, session, fs_storage):
    import base64 as b64

    _, asset = await mk_html_bundle(
        client, session, {"index.html": b"<html></html>", "img/logo.png": _PNG_BYTES}
    )

    r = await client.get(
        f"/api/assets/by-slug/{asset.slug}/file-mcp?path=img/logo.png&encoding=base64"
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["encoding"] == "base64"
    assert body["mime"] == "image/png"
    assert body["size_bytes"] == len(_PNG_BYTES)
    assert b64.b64decode(body["content_base64"]) == _PNG_BYTES
    assert "content" not in body


@pytest.mark.asyncio
async def test_file_mcp_bundle_binary_over_base64_cap_413(client, session, fs_storage):
    big = b"\xff\xfe" * (600 * 1024)  # ~1.2 MB invalid UTF-8
    _, asset = await mk_html_bundle(
        client, session, {"index.html": b"<html></html>", "media/big.woff2": big}
    )

    r = await client.get(
        f"/api/assets/by-slug/{asset.slug}/file-mcp?path=media/big.woff2&encoding=base64"
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_file_mcp_bundle_markdown_format_extracts_content(client, session, fs_storage):
    html = b"""<html><head><title>t</title><style>body{}</style></head><body>
<script>console.log("noise")</script>
<h1>Title</h1><p>Paragraph text.</p>
<table><tr><th>Col A</th><th>Col B</th></tr><tr><td>1</td><td>2</td></tr></table>
</body></html>"""
    _, asset = await mk_html_bundle(client, session, {"index.html": html})

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?format=markdown")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "markdown"
    content = body["content"]
    assert "# Title" in content
    assert "Paragraph text." in content
    assert "Col A" in content and "|" in content  # the table has a pipe representation
    assert "console.log" not in content
    assert "<h1>" not in content and "body{}" not in content


@pytest.mark.asyncio
async def test_file_mcp_markdown_format_rejected_for_non_html(client, session, fs_storage):
    _, asset = await mk_html_bundle(
        client, session, {"index.html": b"<html></html>", "assets/style.css": b"body{}"}
    )

    r = await client.get(
        f"/api/assets/by-slug/{asset.slug}/file-mcp?path=assets/style.css&format=markdown"
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_file_mcp_max_lines_raises_default_cap(client, session, fs_storage):
    body_bytes = "\n".join(f"line {i}" for i in range(1, 2501)).encode()  # 2500 lines
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await session.commit()
    await put_blob(asset, "doc.md", body_bytes)
    await _login(client, user)

    # Default 2000 -> explicit 400 with pagination instructions.
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp")
    assert r.status_code == 400

    # Raised limit -> everything in one request.
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?max_lines=2500")
    assert r.status_code == 200
    body = r.json()
    assert body["total_lines"] == 2500
    assert body["returned_range"] == [1, 2500]


@pytest.mark.asyncio
async def test_file_mcp_max_lines_above_ceiling_422(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await session.commit()
    await put_blob(asset, "doc.md", b"x")
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?max_lines=999999")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_file_mcp_bundle_oneliner_over_text_cap_413(client, session, fs_storage):
    minified = b"var a=1;" * (80 * 1024)  # ~640 KB in a single line
    _, asset = await mk_html_bundle(
        client, session, {"index.html": b"<html></html>", "app.js": minified}
    )

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp?path=app.js")
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_file_mcp_404_on_missing_file(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    # Storage never got the entry, so the endpoint should return 404.
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_file_mcp_collection_requires_path_when_no_entry(client, session, fs_storage):
    """md_collection without entry_path and without `path=...` -> 400."""
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_collection", entry_path=None)
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp")
    assert r.status_code == 400
    assert r.json()["code"] == "path_required"


# ============================================================
#  /by-slug/{slug}/outline
# ============================================================


@pytest.mark.asyncio
async def test_outline_returns_cached_fresh(client, session, fs_storage):
    """Asset with outline_status=fresh and matching version -> 200 with ETag."""
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.outline_status = "fresh"
    asset.outline_version = asset.version
    asset.outline_json = {"items": [{"title": "h1", "level": 1}]}
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/outline")
    assert r.status_code == 200
    # The outline version plus a digest of the freshness and relation block.
    assert r.headers["ETag"].startswith(f'W/"outline-v{asset.outline_version}-')
    body = r.json()
    assert body["items"] == [{"title": "h1", "level": 1}]
    assert body["freshness"] == "current"
    assert body["superseded_by"] is None
    assert body["edges"] == []


@pytest.mark.asyncio
async def test_outline_304_on_etag_match(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.outline_status = "fresh"
    asset.outline_version = asset.version
    asset.outline_json = {"items": []}
    await session.commit()
    await _login(client, user)

    etag = (await client.get(f"/api/assets/by-slug/{asset.slug}/outline")).headers["ETag"]
    r = await client.get(
        f"/api/assets/by-slug/{asset.slug}/outline",
        headers={"if-none-match": etag},
    )
    assert r.status_code == 304


@pytest.mark.asyncio
async def test_outline_failed_returns_500(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.outline_status = "failed"
    asset.outline_error = "parse error: invalid YAML frontmatter"
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/outline")
    assert r.status_code == 500
    body = r.json()
    assert body["status"] == "failed"
    assert "parse error" in body["error"]


@pytest.mark.asyncio
async def test_outline_stale_returns_payload_with_x_outline_stale(
    client, session, fs_storage, monkeypatch
):
    """Asset with a stale outline but `outline_json IS NOT NULL` -> 200 with
    the old content + X-Outline-Stale header."""
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.outline_status = "stale"
    asset.outline_version = 1
    asset.version = 2  # newer version than the outline
    asset.outline_json = {"items": [{"title": "old", "level": 1}]}
    await session.commit()
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/outline")
    assert r.status_code == 200
    assert r.headers.get("X-Outline-Stale") == "true"
    assert r.headers.get("X-Outline-Version") == "1"
    assert r.headers.get("X-Asset-Version") == "2"


@pytest.mark.asyncio
async def test_outline_building_returns_202_with_retry_after(
    client, session, fs_storage, monkeypatch
):
    """Asset with `outline_json IS NULL` -> enqueue + 202 with Retry-After."""
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.outline_status = "stale"
    asset.outline_json = None
    await session.commit()

    # Mock enqueue so no real arq worker is needed.
    calls = []

    async def _fake_enqueue(name, *args, **kwargs):
        calls.append((name, args, kwargs))

    monkeypatch.setattr("app.routes.mcp_assets.outline.enqueue", _fake_enqueue)
    await _login(client, user)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/outline")
    assert r.status_code == 202
    assert r.headers.get("Retry-After") == "2"
    body = r.json()
    assert body["status"] == "building"
    assert len(calls) == 1
    assert calls[0][0] == "rebuild_outline"


@pytest.mark.asyncio
async def test_outline_rebuild_post_enqueues_and_marks_stale(
    client, session, fs_storage, monkeypatch
):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.outline_status = "fresh"  # a manual rebuild switches it to stale
    asset.outline_version = asset.version
    asset.outline_json = {"items": []}
    await session.commit()

    calls = []

    async def _fake_enqueue(name, *args, **kwargs):
        calls.append(name)

    monkeypatch.setattr("app.routes.mcp_assets.outline.enqueue", _fake_enqueue)
    await _login(client, user)

    r = await client.post(f"/api/assets/{asset.id}/outline/rebuild")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "scheduled"
    assert body["asset_id"] == str(asset.id)
    assert calls == ["rebuild_outline"]

    # The asset was marked stale in the database.
    await session.refresh(asset)
    assert asset.outline_status == "stale"
