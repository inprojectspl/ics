"""Office documents: upload, format detection, validation, new version and
restore. The MCP server uploads through the same `POST /api/assets/document`
and lists through `/api/assets/index`, so both are covered here."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Asset, ShareLink
from app.services import documents
from app.storage import storage_from_url
from tests.conftest import login_as, mk_user
from tests.office_factory import doc_text, make_doc, make_docx, make_odt, office_file


async def _signed_in(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    return user


async def _upload(client, name, data, query=""):
    return await client.post(f"/api/assets/document{query}", files=office_file(name, data))


async def _read_md(client, slug, query=""):
    r = await client.get(f"/api/assets/by-slug/{slug}/file-mcp{query}")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "data", "fmt"),
    [
        ("Offer.docx", make_docx([("h1", "Offer"), ("p", "Body text")]), "docx"),
        ("Notes.odt", make_odt([("h1", "Offer"), ("p", "Body text")]), "odt"),
        ("Legacy.doc", make_doc(doc_text(["Offer", "Body text"])), "doc"),
    ],
    ids=["docx", "odt", "doc"],
)
async def test_upload_creates_office_asset_listed_with_its_kind(
    client, session, fs_storage, name, data, fmt
):
    await _signed_in(client, session)
    r = await _upload(client, name, data)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "office_doc"
    assert body["title"] == name.rsplit(".", 1)[0]
    assert body["source_format"] == fmt
    assert body["security_status"] == "clean"
    assert body["share_url"].startswith("http")

    index = await client.get("/api/assets/index?kind=office_doc")
    assert [(i["slug"], i["kind"]) for i in index.json()["items"]] == [(body["slug"], "office_doc")]
    assert "Body text" in (await _read_md(client, body["slug"]))["content"]


@pytest.mark.asyncio
async def test_format_is_taken_from_the_content(client, session, fs_storage):
    await _signed_in(client, session)
    r = await _upload(client, "misnamed.docx", make_odt([("p", "really an odt")]))
    assert r.status_code == 201, r.text
    assert r.json()["source_format"] == "odt"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("notes.txt", b"plain text", 400, "office_file_required"),
        ("fake.docx", b"%PDF-1.7 not a word file", 400, "invalid_office_document"),
        ("broken.docx", b"PK\x03\x04 truncated archive", 400, "invalid_office_document"),
        ("locked.doc", make_doc(doc_text(["x"]), encrypted=True), 400, "office_encrypted"),
        ("locked.odt", make_odt([("p", "x")], encrypted=True), 400, "office_encrypted"),
    ],
    ids=["extension", "pdf-content", "broken-zip", "encrypted-doc", "encrypted-odt"],
)
async def test_invalid_uploads_are_rejected_and_leave_nothing_behind(
    client, session, fs_storage, name, data, status, code
):
    user = await _signed_in(client, session)
    r = await _upload(client, name, data)
    assert r.status_code == status
    assert r.json()["code"] == code
    storage = storage_from_url(get_settings().storage_url)
    assert await storage.list_prefix("assets/") == []
    assert await session.scalar(select(Asset).where(Asset.owner_id == user.id)) is None


@pytest.mark.asyncio
async def test_document_over_the_size_cap_is_rejected(client, session, fs_storage, monkeypatch):
    await _signed_in(client, session)
    monkeypatch.setattr(get_settings(), "office_max_bytes", 100)
    r = await _upload(client, "big.docx", make_docx([("p", "x" * 500)]))
    assert r.status_code == 413
    assert r.json()["code"] == "office_too_large"


@pytest.mark.asyncio
async def test_macros_block_the_default_share(client, session, fs_storage):
    user = await _signed_in(client, session)
    r = await _upload(client, "macro.docx", make_docx([("p", "x")], macros=True))
    assert r.status_code == 201
    assert r.json()["security_status"] == "critical"
    assert r.json()["share_url"] is None
    asset = await session.scalar(select(Asset).where(Asset.owner_id == user.id))
    assert asset is not None
    shares = (await session.scalars(select(ShareLink).where(ShareLink.asset_id == asset.id))).all()
    assert shares == []
    assert [f["code"] for f in asset.security_report["findings"]] == ["office_macros"]


@pytest.mark.asyncio
async def test_new_version_in_another_format_and_restore(client, session, fs_storage):
    await _signed_in(client, session)
    created = (await _upload(client, "plan.docx", make_docx([("p", "first draft")]))).json()
    asset_id, slug = created["id"], created["slug"]

    r = await client.post(
        f"/api/assets/{asset_id}/versions",
        files=[
            ("files", ("plan.odt", make_odt([("p", "second draft")]), "application/octet-stream"))
        ],
    )
    assert r.status_code == 201, r.text
    assert r.json()["entry_path"] == "plan.odt"
    assert "second draft" in (await _read_md(client, slug))["content"]

    r = await client.post(f"/api/assets/{asset_id}/versions/1/restore")
    assert r.status_code == 201, r.text
    restored = await _read_md(client, slug)
    assert restored["version"] == 3
    assert "first draft" in restored["content"]
    assert "second draft" not in restored["content"]
    assert restored["format"] == "markdown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("files", "code"),
    [
        ([("files", ("n.md", b"# md", "text/markdown"))], "office_file_required"),
        (
            [("files", ("f.docx", b"garbage", "application/octet-stream"))],
            "invalid_office_document",
        ),
        (
            [
                ("files", ("a.docx", make_docx([("p", "a")]), "application/octet-stream")),
                ("files", ("b.docx", make_docx([("p", "b")]), "application/octet-stream")),
            ],
            "office_file_required",
        ),
    ],
    ids=["markdown", "garbage", "two-files"],
)
async def test_invalid_new_version_keeps_the_current_one(client, session, fs_storage, files, code):
    await _signed_in(client, session)
    created = (await _upload(client, "kept.docx", make_docx([("p", "kept text")]))).json()
    r = await client.post(f"/api/assets/{created['id']}/versions", files=files)
    assert r.status_code == 400
    assert r.json()["code"] == code
    current = await _read_md(client, created["slug"])
    assert current["version"] == 1
    assert "kept text" in current["content"]
    asset = await session.scalar(select(Asset).where(Asset.slug == created["slug"]))
    assert asset is not None
    storage = storage_from_url(get_settings().storage_url)
    assert await storage.list_prefix(f"{documents.derived_prefix(asset.storage_prefix, 2)}/") == []


@pytest.mark.asyncio
async def test_office_document_has_no_editable_source(client, session, fs_storage):
    await _signed_in(client, session)
    created = (await _upload(client, "x.docx", make_docx([("p", "x")]))).json()
    source = await client.get(f"/api/assets/by-slug/{created['slug']}/source")
    assert source.status_code == 400
    assert source.json()["code"] == "office_not_editable"
    edit = await client.put(f"/api/assets/{created['id']}/content", json={"content": "x"})
    assert edit.status_code == 400
    assert edit.json()["code"] == "office_not_editable"
