"""PDF assets: upload, validation, new version and restore.

The MCP server uploads through the same `POST /api/assets/pdf` and lists
through `/api/assets/index`, so both are covered here.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Asset, ShareLink
from app.services import documents
from app.storage import storage_from_url
from tests.conftest import login_as, mk_user
from tests.pdf_factory import make_pdf, pdf_file


async def _signed_in(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    return user


async def _upload(client, name="report.pdf", data=None, query=""):
    return await client.post(
        f"/api/assets/pdf{query}", files=pdf_file(name, data or make_pdf(["Quarterly report"]))
    )


async def _read_md(client, slug, query=""):
    r = await client.get(f"/api/assets/by-slug/{slug}/file-mcp{query}")
    assert r.status_code == 200, r.text
    return r.json()


async def _stored_keys(user) -> list[str]:
    storage = storage_from_url(get_settings().storage_url)
    return await storage.list_prefix("assets/")


@pytest.mark.asyncio
async def test_upload_creates_pdf_asset_listed_with_its_kind(client, session, fs_storage):
    await _signed_in(client, session)

    r = await _upload(client, data=make_pdf(["One", "Two"]))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "pdf_doc"
    assert body["title"] == "report"
    assert body["page_count"] == 2
    assert body["text_page_count"] == 2
    assert body["security_status"] == "clean"
    assert body["share_url"].startswith("http")

    index = await client.get("/api/assets/index?kind=pdf_doc")
    assert index.status_code == 200
    assert [(i["slug"], i["kind"]) for i in index.json()["items"]] == [(body["slug"], "pdf_doc")]

    listing = await client.get("/api/assets")
    kinds = {i["slug"]: i["kind"] for i in listing.json()["items"]}
    assert kinds[body["slug"]] == "pdf_doc"

    asset = await session.scalar(select(Asset).where(Asset.slug == body["slug"]))
    assert asset is not None
    assert asset.entry_path == "report.pdf"
    meta = await documents.load_meta(asset, 1, get_settings())
    assert (meta["page_count"], meta["text_page_count"]) == (2, 2)
    markdown = await documents.markdown(asset, 1, get_settings())
    assert "## Page 1\n\nOne" in markdown
    assert "## Page 2\n\nTwo" in markdown


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("notes.md", b"# not a pdf", 400, "pdf_file_required"),
        ("fake.pdf", b"PK\x03\x04 zip bytes renamed to pdf", 400, "invalid_pdf"),
        ("broken.pdf", b"%PDF-1.7\ntruncated", 400, "invalid_pdf"),
        (
            "locked.pdf",
            make_pdf(["secret"], user_password="pw", owner_password="owner"),
            400,
            "pdf_encrypted",
        ),
    ],
    ids=["wrong-extension", "no-signature", "unparseable", "password-protected"],
)
async def test_invalid_uploads_are_rejected_and_leave_nothing_behind(
    client, session, fs_storage, name, data, status, code
):
    user = await _signed_in(client, session)
    r = await _upload(client, name=name, data=data)
    assert r.status_code == status
    assert r.json()["code"] == code
    assert await _stored_keys(user) == []
    assert await session.scalar(select(Asset).where(Asset.owner_id == user.id)) is None


@pytest.mark.asyncio
async def test_pdf_over_the_size_cap_is_rejected(client, session, fs_storage, monkeypatch):
    await _signed_in(client, session)
    monkeypatch.setattr(get_settings(), "pdf_max_bytes", 200)
    r = await _upload(client)
    assert r.status_code == 413
    assert r.json()["code"] == "pdf_too_large"


@pytest.mark.asyncio
async def test_launch_action_blocks_the_default_share(client, session, fs_storage):
    user = await _signed_in(client, session)
    r = await _upload(client, data=make_pdf(["run me"], launch=True))
    assert r.status_code == 201
    assert r.json()["security_status"] == "critical"
    assert r.json()["share_url"] is None
    asset = await session.scalar(select(Asset).where(Asset.owner_id == user.id))
    assert asset is not None
    shares = (await session.scalars(select(ShareLink).where(ShareLink.asset_id == asset.id))).all()
    assert shares == []
    assert [f["code"] for f in asset.security_report["findings"]] == ["pdf_launch_action"]


@pytest.mark.asyncio
async def test_new_version_and_restore_rebuild_the_text(client, session, fs_storage):
    await _signed_in(client, session)
    created = (await _upload(client, data=make_pdf(["first edition"]))).json()
    asset_id, slug = created["id"], created["slug"]

    r = await client.post(
        f"/api/assets/{asset_id}/versions",
        files=[
            ("files", ("second.pdf", make_pdf(["second edition", "appendix"]), "application/pdf"))
        ],
    )
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 2
    assert r.json()["entry_path"] == "second.pdf"
    current = await _read_md(client, slug)
    assert "second edition" in current["content"]
    assert current["page_count"] == 2

    r = await client.post(f"/api/assets/{asset_id}/versions/1/restore")
    assert r.status_code == 201, r.text
    restored = await _read_md(client, slug)
    assert restored["version"] == 3
    assert "first edition" in restored["content"]
    assert "second edition" not in restored["content"]

    search = await client.get("/api/assets/search-mcp?q=edition")
    hit = next(i for i in search.json()["items"] if i["slug"] == slug)
    assert "first" in hit["snippets"][0]["text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("files", "code"),
    [
        ([("files", ("doc.md", b"# md", "text/markdown"))], "pdf_file_required"),
        ([("files", ("fake.pdf", b"not a pdf at all", "application/pdf"))], "invalid_pdf"),
        (
            [
                ("files", ("a.pdf", make_pdf(["a"]), "application/pdf")),
                ("files", ("b.pdf", make_pdf(["b"]), "application/pdf")),
            ],
            "pdf_file_required",
        ),
    ],
    ids=["markdown", "not-a-pdf", "two-files"],
)
async def test_invalid_new_version_keeps_the_current_one(client, session, fs_storage, files, code):
    await _signed_in(client, session)
    created = (await _upload(client, data=make_pdf(["kept text"]))).json()

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
async def test_pdf_has_no_editable_source(client, session, fs_storage):
    await _signed_in(client, session)
    created = (await _upload(client)).json()

    source = await client.get(f"/api/assets/by-slug/{created['slug']}/source")
    assert source.status_code == 400
    assert source.json()["code"] == "pdf_not_editable"
    edit = await client.put(f"/api/assets/{created['id']}/content", json={"content": "x"})
    assert edit.status_code == 400
    assert edit.json()["code"] == "pdf_not_editable"
