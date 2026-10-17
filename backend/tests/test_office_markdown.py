"""Office documents as Markdown for MCP clients (`file-mcp`, share resolve).

The structure that matters to an agent survives the conversion: headings,
lists, tables and footnotes from .docx and .odt; paragraphs and table rows
from the legacy .doc. Images are never read, only marked.
"""

from __future__ import annotations

import base64

import pytest

from app.office_extract import IMAGE_MARKER
from tests.conftest import login_as, mk_user
from tests.office_factory import doc_text, make_doc, make_docx, make_odt, office_file

BLOCKS = [
    ("h1", "Project plan"),
    ("p", "Scope of the work."),
    ("li", "first item"),
    ("li", "second item"),
    ("h2", "Budget"),
    ("table", [["Item", "Cost"], ["GIS platform", "100"]]),
    ("img",),
    ("fn", "Deadline is fixed", "Agreed in the kickoff"),
]


async def _upload(client, session, name, data):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post("/api/assets/document", files=office_file(name, data))
    assert r.status_code == 201, r.text
    return r.json()


async def _file_mcp(client, slug, query=""):
    r = await client.get(f"/api/assets/by-slug/{slug}/file-mcp{query}")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "data"),
    [("plan.docx", make_docx(BLOCKS)), ("plan.odt", make_odt(BLOCKS))],
    ids=["docx", "odt"],
)
async def test_structure_survives_as_markdown(client, session, fs_storage, name, data):
    created = await _upload(client, session, name, data)
    body = await _file_mcp(client, created["slug"], "?path=ignored.md")
    md = body["content"]
    assert body["format"] == "markdown"
    assert body["path"] == name
    assert body["images"] == 1
    lines = md.splitlines()
    assert lines[0] == "# plan"
    assert "# Project plan" in lines
    assert "## Budget" in lines
    assert "- first item" in lines
    assert "- second item" in lines
    assert "| Item | Cost |" in lines
    assert "| GIS platform | 100 |" in lines
    assert f"*{IMAGE_MARKER}*" in lines
    assert "Deadline is fixed[1]" in lines
    assert any("Agreed in the kickoff" in line for line in lines)


@pytest.mark.asyncio
async def test_legacy_doc_keeps_paragraphs_and_table_rows(client, session, fs_storage):
    text = doc_text(
        ["Legacy offer", 'Price list \x13 HYPERLINK "http://x" \x14below\x15:', "# not a heading"],
        rows=[["Service", "Price"], ["Hosting", "10"]],
        trailer=["Signed \x01"],
    )
    created = await _upload(client, session, "offer.doc", make_doc(text))
    md = (await _file_mcp(client, created["slug"]))["content"]
    assert md.splitlines() == [
        "# offer",
        "",
        "Legacy offer",
        "",
        "Price list below:",
        "",
        "\\# not a heading",
        "",
        "| Service | Price |",
        "| --- | --- |",
        "| Hosting | 10 |",
        "",
        f"Signed {IMAGE_MARKER}",
    ]


@pytest.mark.asyncio
async def test_markdown_is_paginated_and_archived_versions_read_their_text(
    client, session, fs_storage
):
    created = await _upload(
        client, session, "long.docx", make_docx([("p", f"paragraph {n}") for n in range(1, 30)])
    )
    first = await _file_mcp(client, created["slug"], "?lines=1-3")
    assert first["returned_range"] == [1, 3]
    assert first["content"].splitlines() == ["# long", "", "paragraph 1"]
    assert first["total_lines"] > 50

    r = await client.post(
        f"/api/assets/{created['id']}/versions",
        files=[
            ("files", ("long.docx", make_docx([("p", "rewritten")]), "application/octet-stream"))
        ],
    )
    assert r.status_code == 201
    old = await _file_mcp(client, created["slug"], "?version=1")
    assert "paragraph 29" in old["content"]
    assert old["current_version"] == 2
    assert "rewritten" in (await _file_mcp(client, created["slug"]))["content"]


@pytest.mark.asyncio
async def test_raw_document_needs_base64(client, session, fs_storage):
    data = make_docx([("p", "raw")])
    created = await _upload(client, session, "raw.docx", data)
    refused = await client.get(f"/api/assets/by-slug/{created['slug']}/file-mcp?format=raw")
    assert refused.status_code == 415
    assert refused.json()["code"] == "binary_file"
    raw = await _file_mcp(client, created["slug"], "?format=raw&encoding=base64")
    assert base64.b64decode(raw["content_base64"]) == data
    assert raw["mime"].startswith("application/vnd.openxmlformats")


@pytest.mark.asyncio
async def test_share_resolve_returns_the_markdown(client, session, fs_storage):
    created = await _upload(client, session, "shared.odt", make_odt([("p", "for agents")]))
    token = created["share_url"].rstrip("/").rsplit("/", 1)[-1]
    r = await client.post(f"/api/share/{token}/resolve", json={})
    assert r.status_code == 200, r.text
    assert r.json()["asset"]["kind"] == "office_doc"
    assert "for agents" in r.json()["content"]
