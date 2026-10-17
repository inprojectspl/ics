"""The PDF as Markdown for MCP clients: `file-mcp`, `files-mcp`, share resolve.

An agent cannot read a binary PDF, so ICS serves its extracted text as
Markdown with one `## Page N` section per page, paginated like any other
text file and available for archived versions.
"""

from __future__ import annotations

import base64

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Asset
from app.pdf_markdown import NO_TEXT_NOTE, TRUNCATED_NOTE, pdf_to_markdown
from app.services import documents
from app.storage import storage_from_url
from tests.conftest import login_as, mk_user
from tests.pdf_factory import make_pdf, pdf_file


async def _upload(client, session, pages, name="manual.pdf"):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post("/api/assets/pdf", files=pdf_file(name, make_pdf(pages)))
    assert r.status_code == 201, r.text
    return r.json()


async def _file_mcp(client, slug, query=""):
    return await client.get(f"/api/assets/by-slug/{slug}/file-mcp{query}")


@pytest.mark.asyncio
async def test_pdf_reads_as_markdown_with_a_section_per_page(client, session, fs_storage):
    created = await _upload(client, session, ["Intro line\n# not a heading", None, "Final words"])

    r = await _file_mcp(client, created["slug"], "?path=ignored.md")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["format"] == "markdown"
    assert body["path"] == "manual.pdf"
    assert body["page_count"] == 3
    assert body["text_page_count"] == 2
    assert body["content"] == (
        "# manual\n\n"
        "## Page 1\n\nIntro line\n\\# not a heading\n\n"
        f"## Page 2\n\n{NO_TEXT_NOTE}\n\n"
        "## Page 3\n\nFinal words"
    )
    assert body["total_lines"] == len(body["content"].splitlines())


@pytest.mark.asyncio
async def test_markdown_is_paginated_by_lines(client, session, fs_storage):
    created = await _upload(client, session, [f"page {n} text" for n in range(1, 6)])

    first = (await _file_mcp(client, created["slug"], "?lines=1-5")).json()
    assert first["returned_range"] == [1, 5]
    assert first["content"].splitlines() == ["# manual", "", "## Page 1", "", "page 1 text"]
    rest = (await _file_mcp(client, created["slug"], "?lines=6-9")).json()
    assert rest["content"].splitlines()[1] == "## Page 2"
    assert rest["total_lines"] == first["total_lines"]


@pytest.mark.asyncio
async def test_archived_version_reads_its_own_text(client, session, fs_storage):
    created = await _upload(client, session, ["old wording"])
    r = await client.post(
        f"/api/assets/{created['id']}/versions",
        files=[("files", ("manual.pdf", make_pdf(["new wording"]), "application/pdf"))],
    )
    assert r.status_code == 201

    old = (await _file_mcp(client, created["slug"], "?version=1")).json()
    assert "old wording" in old["content"]
    assert old["version"] == 1
    assert old["current_version"] == 2
    new = (await _file_mcp(client, created["slug"])).json()
    assert "new wording" in new["content"]


@pytest.mark.asyncio
async def test_raw_pdf_needs_base64(client, session, fs_storage):
    data = make_pdf(["raw bytes"])
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    slug = (await client.post("/api/assets/pdf", files=pdf_file("raw.pdf", data))).json()["slug"]

    refused = await _file_mcp(client, slug, "?format=raw")
    assert refused.status_code == 415
    assert refused.json()["code"] == "binary_file"
    raw = (await _file_mcp(client, slug, "?format=raw&encoding=base64")).json()
    assert raw["mime"] == "application/pdf"
    assert base64.b64decode(raw["content_base64"]) == data


@pytest.mark.asyncio
async def test_pages_past_the_extraction_limit_are_marked(client, session, fs_storage, monkeypatch):
    monkeypatch.setattr(get_settings(), "pdf_extract_max_pages", 1)
    created = await _upload(client, session, ["kept", "dropped"])
    body = (await _file_mcp(client, created["slug"])).json()
    assert "kept" in body["content"]
    assert "dropped" not in body["content"]
    assert TRUNCATED_NOTE in body["content"]


@pytest.mark.asyncio
async def test_missing_derived_file_is_rebuilt_from_the_pdf(client, session, fs_storage):
    created = await _upload(client, session, ["survives a lost derived file"])
    asset = await session.scalar(select(Asset).where(Asset.slug == created["slug"]))
    assert asset is not None
    storage = storage_from_url(get_settings().storage_url)
    derived = documents.derived_prefix(asset.storage_prefix, 1)
    await storage.delete_prefix(derived)

    body = (await _file_mcp(client, created["slug"])).json()
    assert "survives a lost derived file" in body["content"]
    assert body["page_count"] == 1
    assert len(await storage.list_prefix(f"{derived}/")) == 2


@pytest.mark.asyncio
async def test_files_mcp_lists_the_pdf(client, session, fs_storage):
    created = await _upload(client, session, ["x"])
    r = await client.get(f"/api/assets/by-slug/{created['slug']}/files-mcp")
    assert r.status_code == 200, r.text
    assert r.json()["entry_path"] == "manual.pdf"
    assert [f["path"] for f in r.json()["files"]] == ["manual.pdf"]


@pytest.mark.asyncio
async def test_share_resolve_returns_the_markdown(client, session, fs_storage):
    created = await _upload(client, session, ["shared text for agents"])
    share_url = created["share_url"]
    token = share_url.rstrip("/").rsplit("/", 1)[-1]

    r = await client.post(f"/api/share/{token}/resolve", json={})
    assert r.status_code == 200, r.text
    assert r.json()["asset"]["kind"] == "pdf_doc"
    assert "## Page 1" in r.json()["content"]
    assert "shared text for agents" in r.json()["content"]


def test_markdown_escapes_line_starts_markdown_would_interpret():
    md = pdf_to_markdown("T", ["> quote\n- item\n1. step\n  # indented\nplain"])
    assert md.splitlines()[4:] == ["\\> quote", "\\- item", "\\1. step", "  \\# indented", "plain"]
    assert pdf_to_markdown(None, []) == "# PDF document\n"
