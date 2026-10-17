"""PDF search hits with page numbers, and the PDF outline.

`search-mcp` matches the extracted text and says which page a snippet comes
from; the outline lists the PDF's bookmarks with pages plus the `## Page N`
headings of the Markdown that `file-mcp` serves, with their line numbers.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.jobs.tasks import outline as outline_mod
from app.models import Asset
from app.outline_parser import cap_outline
from app.pdf_markdown import snippet_probe
from app.routes.mcp_assets.search import _snippet_position
from tests.conftest import login_as, mk_user
from tests.pdf_factory import make_pdf, pdf_file


async def _upload(client, session, data, name="atlas.pdf"):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post("/api/assets/pdf", files=pdf_file(name, data))
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_search_returns_the_pdf_with_snippet_and_page(client, session, fs_storage):
    pages = [
        "Chapter one talks about rivers and mountains in general terms.",
        "Nothing relevant here, only filler text about weather patterns.",
        "The platypus is a semiaquatic egg laying mammal endemic to eastern Australia.",
    ]
    created = await _upload(client, session, make_pdf(pages))

    r = await client.get("/api/assets/search-mcp?q=platypus")
    assert r.status_code == 200, r.text
    hits = [i for i in r.json()["items"] if i["slug"] == created["slug"]]
    assert len(hits) == 1
    assert hits[0]["kind"] == "pdf_doc"
    snippet = hits[0]["snippets"][0]
    assert "<em>platypus</em>" in snippet["text"]
    assert snippet["page"] == 3

    filtered = await client.get("/api/assets/search-mcp?q=platypus&kind=pdf_doc")
    assert [i["slug"] for i in filtered.json()["items"]] == [created["slug"]]


@pytest.mark.asyncio
async def test_markdown_hits_have_no_page(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post(
        "/api/assets", files={"file": ("wombat.md", b"# Wombat\n\nwombat burrows", "text/markdown")}
    )
    assert r.status_code == 201
    hits = (await client.get("/api/assets/search-mcp?q=burrows")).json()["items"]
    assert hits[0]["snippets"][0]["page"] is None


@pytest.mark.asyncio
async def test_snippet_page_handles_titles_repeats_and_page_breaks(client, session, fs_storage):
    pages = [
        "Opening words about the harbour.",
        "Quokka sightings are rare here but the quokka is friendly.",
        "Tail end of the report with closing remarks.",
    ]
    created = await _upload(client, session, make_pdf(pages), name="Harbour notes.pdf")
    asset = await session.scalar(select(Asset).where(Asset.slug == created["slug"]))
    assert asset is not None

    async def page(snippet: str) -> int | None:
        return await _snippet_position(session, asset.id, snippet, "\f")

    # The fragment starts in the title; the highlight decides.
    assert await page("Harbour notes Opening words about the <em>harbour</em>.") == 1
    assert await page("the <em>quokka</em> is friendly") == 2
    # A phrase across a page break belongs to the page where it starts.
    assert await page("the <em>quokka</em> is friendly. Tail end") == 2
    assert await page("<em>closing</em> remarks") == 3
    # Words that do not follow each other fall back to the bare term.
    assert await page("<em>remarks</em> nowhere near") == 3
    assert await page("no highlight at all") is None


def test_snippet_probe_escapes_regex_characters():
    assert snippet_probe("x <b>a+b</b> (c) ... d", start_sel="<b>", stop_sel="</b>") == (
        r"a\+b\s+\(c\)",
        "a+b",
    )
    assert snippet_probe("<b></b>", start_sel="<b>", stop_sel="</b>") is None


@pytest.mark.asyncio
async def test_outline_lists_bookmarks_with_pages_and_page_headings(
    client, session, fs_storage, monkeypatch
):
    data = make_pdf(
        ["Intro text", "Method text", "Results text"],
        bookmarks=[("Introduction", 0, 1), ("Method", 1, 1), ("Results", 2, 2)],
    )
    created = await _upload(client, session, data)
    monkeypatch.setattr(
        outline_mod, "SessionLocal", async_sessionmaker(session.bind, expire_on_commit=False)
    )
    asset = await session.scalar(select(Asset).where(Asset.slug == created["slug"]))
    assert asset is not None

    result = await outline_mod.rebuild_outline({}, str(asset.id))
    assert result.get("outline_version") == 1
    session.expire_all()
    r = await client.get(f"/api/assets/by-slug/{created['slug']}/outline")
    assert r.status_code == 200, r.text
    outline = r.json()
    assert outline["kind"] == "pdf_doc"
    assert outline["page_count"] == 3
    assert outline["text_page_count"] == 3
    assert outline["bookmarks"] == [
        {"level": 1, "title": "Introduction", "page": 1},
        {"level": 1, "title": "Method", "page": 2},
        {"level": 2, "title": "Results", "page": 3},
    ]
    page_headings = [h for h in outline["headings"] if h["level"] == 2]
    assert [h["text"] for h in page_headings] == ["Page 1", "Page 2", "Page 3"]

    md = (await client.get(f"/api/assets/by-slug/{created['slug']}/file-mcp")).json()["content"]
    lines = md.splitlines()
    for heading in page_headings:
        assert lines[heading["line"] - 1] == f"## {heading['text']}"


def test_oversized_outline_keeps_top_bookmark_levels():
    outline = {
        "kind": "pdf_doc",
        "headings": [],
        "bookmarks": [{"level": 1 + (i % 3), "title": "x" * 400, "page": i} for i in range(2000)],
        "truncated": False,
    }
    capped = cap_outline(outline)
    assert capped["truncated"] is True
    assert {b["level"] for b in capped["bookmarks"]} == {1, 2}
