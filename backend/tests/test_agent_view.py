"""`GET /by-slug/{slug}/agent-view`: the owner's preview of what an MCP
agent reads through `file-mcp`.

The contract that matters is equality with `file-mcp`: the preview must show
the agent's text, not a similar one.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app import render_cache
from app.collections_io import count_line_reads
from app.models import AssetShare
from tests.conftest import login_as, mk_asset, mk_html_bundle, mk_md_collection, mk_user, put_blob
from tests.pdf_factory import make_pdf, pdf_file

PAGE = (
    b"<html><head><style>p{color:red}</style><script>alert(1)</script></head>"
    b"<body><h1>Report</h1><p>Revenue <b>up</b></p><ul><li>one</li></ul></body></html>"
)


async def _agent_view(client, slug, query=""):
    return await client.get(f"/api/assets/by-slug/{slug}/agent-view{query}")


async def _file_mcp(client, slug, query=""):
    r = await client.get(f"/api/assets/by-slug/{slug}/file-mcp{query}")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
async def test_bundle_page_as_markdown_matches_file_mcp(client, session, fs_storage):
    _, asset = await mk_html_bundle(client, session, {"index.html": PAGE})

    r = await _agent_view(client, asset.slug, "?format=markdown")
    assert r.status_code == 200, r.text
    body = r.json()
    agent = await _file_mcp(client, asset.slug, "?format=markdown")
    assert body["content"] == agent["content"]
    assert body["total_lines"] == agent["total_lines"]
    assert body["format"] == "markdown"
    assert body["html"] is not None
    assert body["path"] == "index.html"
    assert body["agent_reads"] == 1
    assert body["truncated"] is False
    assert "<h1" in body["html"] and "Report" in body["html"]
    assert "alert(1)" not in body["content"]


@pytest.mark.asyncio
async def test_raw_html_is_plain_text_without_render(client, session, fs_storage):
    _, asset = await mk_html_bundle(client, session, {"index.html": PAGE})

    body = (await _agent_view(client, asset.slug)).json()
    assert body["content"] == (await _file_mcp(client, asset.slug))["content"]
    assert body["html"] is None
    assert "format" not in body


@pytest.mark.asyncio
async def test_collection_file_by_path_matches_file_mcp(client, session, fs_storage):
    files = {"README.md": "# Start\n\nsee [[notes]]\n", "notes.md": "# Notes\r\nline\r\n"}
    _, asset = await mk_md_collection(client, session, files)

    entry = (await _agent_view(client, asset.slug)).json()
    assert entry["path"] == "README.md"
    picked = (await _agent_view(client, asset.slug, "?path=notes.md")).json()
    assert picked["content"] == (await _file_mcp(client, asset.slug, "?path=notes.md"))["content"]
    assert picked["content"] == "# Notes\nline"
    assert "Notes" in picked["html"]


@pytest.mark.asyncio
async def test_pdf_reads_as_its_markdown(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post("/api/assets/pdf", files=pdf_file("manual.pdf", make_pdf(["Intro"])))
    slug = r.json()["slug"]

    body = (await _agent_view(client, slug)).json()
    assert body["content"] == (await _file_mcp(client, slug))["content"]
    assert body["page_count"] == 1
    assert body["html"] is not None
    assert "Page 1" in body["html"]


@pytest.mark.asyncio
async def test_archived_version_reads_its_own_text(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    asset.version = 2
    await session.commit()
    await put_blob(asset, "doc.md", b"old text", version=1)
    await put_blob(asset, "doc.md", b"new text", version=2)
    await login_as(client, user)

    old = (await _agent_view(client, asset.slug, "?version=1")).json()
    assert old["content"] == "old text"
    assert old["version"] == 1
    assert old["current_version"] == 2
    assert (await _agent_view(client, asset.slug)).json()["content"] == "new text"


@pytest.mark.asyncio
async def test_long_file_reports_agent_reads_and_truncation(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await session.commit()
    await put_blob(asset, "doc.md", "\n".join(f"line {i}" for i in range(4500)).encode())
    await login_as(client, user)

    body = (await _agent_view(client, asset.slug)).json()
    assert body["total_lines"] == 4500
    assert body["agent_reads"] == 3
    assert body["lines_per_read"] == 2000

    with patch("app.routes.mcp_assets.agent_view.AGENT_VIEW_MAX_BYTES", 100):
        cut = (await _agent_view(client, asset.slug)).json()
    assert cut["truncated"] is True
    assert cut["total_lines"] == 4500
    assert cut["shown_lines"] == len(cut["content"].splitlines())
    assert cut["estimated_tokens"] == body["estimated_tokens"]
    assert len(cut["content"].encode()) <= 100


def test_line_reads_split_on_line_and_byte_caps():
    assert count_line_reads([]) == 0
    assert count_line_reads([1] * 2000) == 1
    assert count_line_reads([1] * 2001) == 2
    # Three lines of 300 KB: two do not fit one 512 KB read.
    assert count_line_reads([300_000] * 3) == 3
    # Two lines filling the cap exactly with the newline between them: one read.
    assert count_line_reads([100, 411], max_bytes=512) == 1
    assert count_line_reads([100, 412], max_bytes=512) == 2


@pytest.mark.asyncio
async def test_viewer_is_refused(client, session, fs_storage):
    owner = await mk_user(session)
    reader = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    session.add(AssetShare(asset_id=asset.id, user_id=reader.id, role="viewer"))
    await session.commit()
    await put_blob(asset, "doc.md", b"secret")
    await login_as(client, reader)

    assert (await _agent_view(client, asset.slug)).status_code == 404
    # The same reader may still read it the way an agent would.
    assert (await client.get(f"/api/assets/by-slug/{asset.slug}/file-mcp")).status_code == 200


@pytest.mark.asyncio
async def test_editor_share_is_allowed(client, session, fs_storage):
    owner = await mk_user(session)
    editor = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md")
    session.add(AssetShare(asset_id=asset.id, user_id=editor.id, role="editor"))
    await session.commit()
    await put_blob(asset, "doc.md", b"# shared")
    await login_as(client, editor)

    assert (await _agent_view(client, asset.slug)).json()["content"] == "# shared"


@pytest.mark.asyncio
async def test_binary_bundle_file_is_415(client, session, fs_storage):
    png = b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe"
    _, asset = await mk_html_bundle(client, session, {"index.html": PAGE, "logo.png": png})

    r = await _agent_view(client, asset.slug, "?path=logo.png")
    assert r.status_code == 415
    assert r.json()["code"] == "binary_file"


@pytest.mark.asyncio
async def test_markdown_format_on_non_html_is_400(client, session, fs_storage):
    _, asset = await mk_html_bundle(client, session, {"index.html": PAGE, "app.css": b"p{}"})

    r = await _agent_view(client, asset.slug, "?path=app.css&format=markdown")
    assert r.status_code == 400
    assert r.json()["code"] == "html_only"


@pytest.mark.asyncio
async def test_unsupported_kind_is_400(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="mystery_kind")
    await session.commit()
    await login_as(client, user)

    r = await _agent_view(client, asset.slug)
    assert r.status_code == 400
    assert r.json()["code"] == "unsupported_kind"


@pytest.mark.asyncio
async def test_render_is_cached_and_sanitized(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user, kind="md_single", entry_path="doc.md")
    await session.commit()
    await put_blob(
        asset, "doc.md", b"# Title\n\n<script>alert(1)</script>\n\n[x](javascript:alert(1))"
    )
    await login_as(client, user)

    first = (await _agent_view(client, asset.slug)).json()["html"]
    assert "<script" not in first
    assert 'href="javascript' not in first

    with patch.object(
        render_cache, "render_markdown_async", side_effect=AssertionError("rendered again")
    ):
        second = (await _agent_view(client, asset.slug)).json()["html"]
    assert second == first
