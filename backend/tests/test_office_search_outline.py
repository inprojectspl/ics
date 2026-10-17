"""Office documents in search and in the outline."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.jobs.tasks import outline as outline_mod
from app.models import Asset
from tests.conftest import login_as, mk_user
from tests.office_factory import doc_text, make_doc, make_docx, make_odt, office_file


async def _upload(client, session, name, data):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.post("/api/assets/document", files=office_file(name, data))
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("a.docx", make_docx([("h1", "Intro"), ("p", "The axolotl regrows limbs.")])),
        ("a.odt", make_odt([("h1", "Intro"), ("p", "The axolotl regrows limbs.")])),
        ("a.doc", make_doc(doc_text(["Intro", "The axolotl regrows limbs."]))),
    ],
    ids=["docx", "odt", "doc"],
)
async def test_search_finds_the_document_by_its_text(client, session, fs_storage, name, data):
    created = await _upload(client, session, name, data)
    r = await client.get("/api/assets/search-mcp?q=axolotl&kind=office_doc")
    assert r.status_code == 200, r.text
    hits = r.json()["items"]
    assert [h["slug"] for h in hits] == [created["slug"]]
    assert hits[0]["kind"] == "office_doc"
    assert "<em>axolotl</em>" in hits[0]["snippets"][0]["text"]
    assert hits[0]["snippets"][0]["page"] is None


@pytest.mark.asyncio
async def test_outline_lists_document_headings_with_markdown_lines(
    client, session, fs_storage, monkeypatch
):
    data = make_docx(
        [
            ("h1", "Chapter one"),
            ("p", "text"),
            ("h2", "Section A"),
            ("p", "more"),
            ("h1", "Chapter two"),
        ]
    )
    created = await _upload(client, session, "book.docx", data)
    monkeypatch.setattr(
        outline_mod, "SessionLocal", async_sessionmaker(session.bind, expire_on_commit=False)
    )
    asset = await session.scalar(select(Asset).where(Asset.slug == created["slug"]))
    assert asset is not None
    assert (await outline_mod.rebuild_outline({}, str(asset.id))).get("outline_version") == 1
    session.expire_all()

    outline = (await client.get(f"/api/assets/by-slug/{created['slug']}/outline")).json()
    assert outline["kind"] == "office_doc"
    assert outline["source_format"] == "docx"
    headings = [(h["level"], h["text"]) for h in outline["headings"]]
    assert headings == [
        (1, "book"),
        (1, "Chapter one"),
        (2, "Section A"),
        (1, "Chapter two"),
    ]
    md = (await client.get(f"/api/assets/by-slug/{created['slug']}/file-mcp")).json()["content"]
    lines = md.splitlines()
    for heading in outline["headings"]:
        assert lines[heading["line"] - 1].lstrip("#").strip() == heading["text"]
