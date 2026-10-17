"""PDF behind share links (public, password), the owner's PDF endpoint,
download, and delete/undelete."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Asset, ShareLink
from app.slug import generate_token
from tests.conftest import login_as, mk_user
from tests.pdf_factory import make_pdf, pdf_file

PASSWORD = "Secret-Pass-1!"


async def _owner_with_pdf(client, session, data=None):
    owner = await mk_user(session)
    await session.commit()
    await login_as(client, owner)
    r = await client.post(
        "/api/assets/pdf", files=pdf_file("brochure.pdf", data or make_pdf(["Brochure text"]))
    )
    assert r.status_code == 201, r.text
    asset = await session.scalar(select(Asset).where(Asset.slug == r.json()["slug"]))
    assert asset is not None
    return owner, asset


async def _share(client, asset, **body) -> str:
    r = await client.post(f"/api/assets/{asset.id}/shares", json=body)
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _assert_pdf_response(r, data: bytes | None = None) -> None:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in r.headers["content-security-policy"]
    assert r.content.startswith(b"%PDF-")
    if data is not None:
        assert r.content == data


@pytest.mark.asyncio
async def test_public_share_serves_doc_pdf_and_download(client, session, fs_storage):
    data = make_pdf(["Public brochure", None])
    _, asset = await _owner_with_pdf(client, session, data)
    token = await _share(client, asset, mode="public")
    await client.post("/api/auth/logout")

    doc = await client.get(f"/api/share/{token}/doc")
    assert doc.status_code == 200, doc.text
    body = doc.json()
    assert body["kind"] == "pdf_doc"
    assert body["html"] is None
    assert body["pdf"] == {"page_count": 2, "text_page_count": 1, "ocr_page_count": 0}
    assert body["security_report"] is None

    _assert_pdf_response(await client.get(f"/api/share/{token}/pdf"), data)

    download = await client.get(f"/api/share/{token}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["content-disposition"] == f'attachment; filename="{asset.slug}.pdf"'
    assert download.content == data

    share = await session.scalar(select(ShareLink).where(ShareLink.token == token))
    assert share is not None
    await session.refresh(share)
    # The doc counts as the view; fetching the PDF bytes does not.
    assert share.view_count == 1


@pytest.mark.asyncio
async def test_password_share_needs_the_password(client, session, fs_storage):
    _, asset = await _owner_with_pdf(client, session)
    token = await _share(client, asset, mode="password", password=PASSWORD)
    await client.post("/api/auth/logout")

    for path in ("doc", "pdf", "download"):
        r = await client.get(f"/api/share/{token}/{path}")
        assert r.status_code in (401, 403), path
    wrong = await client.post(f"/api/share/{token}/auth", json={"password": "nope-nope-1"})
    assert wrong.status_code == 401

    ok = await client.post(f"/api/share/{token}/auth", json={"password": PASSWORD})
    assert ok.status_code == 200, ok.text
    assert (await client.get(f"/api/share/{token}/doc")).json()["pdf"]["page_count"] == 1
    _assert_pdf_response(await client.get(f"/api/share/{token}/pdf"))


@pytest.mark.asyncio
async def test_critical_pdf_is_withheld_from_share_visitors(client, session, fs_storage):
    owner, asset = await _owner_with_pdf(client, session, make_pdf(["x"], launch=True))
    assert asset.security_status == "critical"
    # Sharing is refused while the PDF awaits review...
    refused = await client.post(f"/api/assets/{asset.id}/shares", json={"mode": "public"})
    assert refused.status_code == 403
    # ...and a link that exists anyway (created before a re-upload) serves nothing.
    token = generate_token()
    session.add(ShareLink(asset_id=asset.id, token=token, mode="public", created_by=owner.id))
    await session.commit()
    await client.post("/api/auth/logout")

    for path in ("pdf", "download"):
        r = await client.get(f"/api/share/{token}/{path}")
        assert r.status_code == 410, path
        assert r.json()["code"] == "bundle_withheld"


@pytest.mark.asyncio
async def test_owner_pdf_endpoint_serves_current_and_archived_versions(client, session, fs_storage):
    first = make_pdf(["first"])
    _, asset = await _owner_with_pdf(client, session, first)
    second = make_pdf(["second"])
    r = await client.post(
        f"/api/assets/{asset.id}/versions",
        files=[("files", ("brochure.pdf", second, "application/pdf"))],
    )
    assert r.status_code == 201

    _assert_pdf_response(await client.get(f"/api/assets/by-slug/{asset.slug}/pdf"), second)
    _assert_pdf_response(await client.get(f"/api/assets/by-slug/{asset.slug}/pdf?version=1"), first)
    doc = (await client.get(f"/api/assets/by-slug/{asset.slug}/doc?version=1")).json()
    assert doc["preview_version"] == 1
    assert doc["pdf"]["page_count"] == 1
    missing = await client.get(f"/api/assets/by-slug/{asset.slug}/pdf?version=9")
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_pdf_endpoint_refuses_other_kinds(client, session, fs_storage):
    owner = await mk_user(session)
    await session.commit()
    await login_as(client, owner)
    r = await client.post("/api/assets", files={"file": ("n.md", b"# n", "text/markdown")})
    slug = r.json()["slug"]
    other = await client.get(f"/api/assets/by-slug/{slug}/pdf")
    assert other.status_code == 400
    assert other.json()["code"] == "pdf_only"


@pytest.mark.asyncio
async def test_delete_and_undelete_pdf(client, session, fs_storage):
    _, asset = await _owner_with_pdf(client, session, make_pdf(["recoverable echidna"]))

    assert (await client.delete(f"/api/assets/{asset.id}")).status_code == 204
    assert (await client.get(f"/api/assets/by-slug/{asset.slug}/pdf")).status_code == 404
    hits = (await client.get("/api/assets/search-mcp?q=echidna")).json()["items"]
    assert hits == []

    restored = await client.post(f"/api/assets/{asset.id}/undelete")
    assert restored.status_code == 200, restored.text
    _assert_pdf_response(await client.get(f"/api/assets/by-slug/{asset.slug}/pdf"))
    hits = (await client.get("/api/assets/search-mcp?q=echidna")).json()["items"]
    assert [h["slug"] for h in hits] == [asset.slug]
