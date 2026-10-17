"""Office documents in the browser: the converted preview (`/doc` html),
share links (public, password), download of the original, the review gate,
and delete/undelete."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Asset, ShareLink
from app.slug import generate_token
from tests.conftest import login_as, mk_user
from tests.office_factory import make_docx, office_file

PASSWORD = "Secret-Pass-1!"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


async def _owner_with_doc(client, session, data=None, name="brief.docx"):
    owner = await mk_user(session)
    await session.commit()
    await login_as(client, owner)
    data = data or make_docx([("h1", "Brief"), ("p", "Body <script>alert(1)</script> text")])
    r = await client.post("/api/assets/document", files=office_file(name, data))
    assert r.status_code == 201, r.text
    asset = await session.scalar(select(Asset).where(Asset.slug == r.json()["slug"]))
    assert asset is not None
    return owner, asset, data


async def _share(client, asset, **body) -> str:
    r = await client.post(f"/api/assets/{asset.id}/shares", json=body)
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _assert_preview(body: dict) -> None:
    assert body["kind"] == "office_doc"
    assert body["document"] == {"source_format": "docx", "images": 0}
    html = body["html"]
    assert "<h1" in html and "Brief" in html
    # Text that looks like markup stays text: sanitized like any Markdown.
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.asyncio
async def test_owner_preview_is_sanitized_html(client, session, fs_storage):
    _, asset, _ = await _owner_with_doc(client, session)
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/doc")
    assert r.status_code == 200, r.text
    _assert_preview(r.json())


@pytest.mark.asyncio
async def test_public_share_serves_preview_and_original(client, session, fs_storage):
    _, asset, data = await _owner_with_doc(client, session)
    token = await _share(client, asset, mode="public")
    await client.post("/api/auth/logout")

    doc = await client.get(f"/api/share/{token}/doc")
    assert doc.status_code == 200, doc.text
    _assert_preview(doc.json())
    assert doc.json()["security_report"] is None

    download = await client.get(f"/api/share/{token}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == DOCX_MIME
    assert download.headers["content-disposition"] == f'attachment; filename="{asset.slug}.docx"'
    assert download.content == data

    share = await session.scalar(select(ShareLink).where(ShareLink.token == token))
    assert share is not None
    await session.refresh(share)
    assert share.view_count == 1


@pytest.mark.asyncio
async def test_password_share_needs_the_password(client, session, fs_storage):
    _, asset, _ = await _owner_with_doc(client, session)
    token = await _share(client, asset, mode="password", password=PASSWORD)
    await client.post("/api/auth/logout")

    for path in ("doc", "download"):
        assert (await client.get(f"/api/share/{token}/{path}")).status_code in (401, 403)
    ok = await client.post(f"/api/share/{token}/auth", json={"password": PASSWORD})
    assert ok.status_code == 200, ok.text
    _assert_preview((await client.get(f"/api/share/{token}/doc")).json())
    assert (await client.get(f"/api/share/{token}/download")).status_code == 200


@pytest.mark.asyncio
async def test_document_with_macros_is_withheld_from_share_visitors(client, session, fs_storage):
    owner, asset, _ = await _owner_with_doc(
        client, session, make_docx([("p", "x")], macros=True), name="macro.docx"
    )
    assert asset.security_status == "critical"
    refused = await client.post(f"/api/assets/{asset.id}/shares", json={"mode": "public"})
    assert refused.status_code == 403
    # The owner still sees the preview, to decide about the review.
    assert (await client.get(f"/api/assets/by-slug/{asset.slug}/doc")).status_code == 200

    token = generate_token()
    session.add(ShareLink(asset_id=asset.id, token=token, mode="public", created_by=owner.id))
    await session.commit()
    await client.post("/api/auth/logout")
    for path in ("doc", "download"):
        r = await client.get(f"/api/share/{token}/{path}")
        assert r.status_code == 410, path
        assert r.json()["code"] == "bundle_withheld"


@pytest.mark.asyncio
async def test_owner_download_and_archived_preview(client, session, fs_storage):
    _, asset, data = await _owner_with_doc(client, session)
    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files=[("files", ("brief.docx", make_docx([("p", "Second")]), "application/octet-stream"))],
    )
    assert r.status_code == 201
    old = (await client.get(f"/api/assets/by-slug/{asset.slug}/doc?version=1")).json()
    assert old["preview_version"] == 1
    assert "Brief" in old["html"]
    assert "Second" in (await client.get(f"/api/assets/by-slug/{asset.slug}/doc")).json()["html"]
    download = await client.get(f"/api/assets/by-slug/{asset.slug}/download")
    assert download.headers["content-type"] == DOCX_MIME
    # The download is the current (second) version's original file.
    assert download.content != data
    assert b"word/document.xml" in download.content


@pytest.mark.asyncio
async def test_delete_and_undelete_document(client, session, fs_storage):
    _, asset, _ = await _owner_with_doc(client, session, make_docx([("p", "recoverable pangolin")]))
    assert (await client.delete(f"/api/assets/{asset.id}")).status_code == 204
    assert (await client.get(f"/api/assets/by-slug/{asset.slug}/doc")).status_code == 404
    assert (await client.get("/api/assets/search-mcp?q=pangolin")).json()["items"] == []

    assert (await client.post(f"/api/assets/{asset.id}/undelete")).status_code == 200
    assert (await client.get(f"/api/assets/by-slug/{asset.slug}/doc")).status_code == 200
    hits = (await client.get("/api/assets/search-mcp?q=pangolin")).json()["items"]
    assert [h["slug"] for h in hits] == [asset.slug]
