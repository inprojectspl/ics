"""`content_updated_at` / `content_updated_by` move only when content changes.

`updated_at` is the technical row timestamp: tags, renames, project moves,
outline rebuilds and scanner writes touch it. The content fields must stay
put on those writes and move on every version, v1 included.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.jobs.tasks import outline as outline_mod
from app.models import Asset, AssetShare, Project, ProjectMember
from app.services import asset_security
from app.slug import generate_slug
from tests.conftest import login_as, mk_admin, mk_asset, mk_user, put_blob
from tests.office_factory import make_docx, office_file
from tests.pdf_factory import make_pdf, pdf_file

PAST = datetime(2020, 1, 1, tzinfo=UTC)


async def _no_enqueue(*_args, **_kwargs):
    return None


@pytest.fixture
def no_jobs(monkeypatch):
    for target in (
        "app.routes.mcp_assets.upload.enqueue",
        "app.routes.mcp_assets.lifecycle.enqueue",
    ):
        monkeypatch.setattr(target, _no_enqueue)


async def _aged_asset(session, owner, **kw) -> Asset:
    """An asset whose row and content timestamps both lie in the past, so a
    write that touches the row is visible in `updated_at`."""
    asset = await mk_asset(session, owner, **kw)
    asset.content_updated_at = PAST
    asset.content_updated_by = owner.id
    asset.updated_at = PAST
    await session.commit()
    return asset


async def _assert_content_untouched(session, asset: Asset, owner_id) -> None:
    await session.refresh(asset)
    assert asset.updated_at > PAST, "the operation did not write the row at all"
    assert asset.content_updated_at == PAST
    assert asset.content_updated_by == owner_id


# ---------- metadata writes leave the content fields alone ----------


@pytest.mark.asyncio
async def test_tags_do_not_change_content_timestamp(client, session):
    owner = await mk_user(session)
    asset = await _aged_asset(session, owner)
    await login_as(client, owner)

    r = await client.put(f"/api/assets/{asset.id}/tags", json={"tags": ["alpha"]})
    assert r.status_code == 200, r.text

    await _assert_content_untouched(session, asset, owner.id)


@pytest.mark.asyncio
async def test_rename_does_not_change_content_timestamp(client, session):
    owner = await mk_user(session)
    asset = await _aged_asset(session, owner)
    await login_as(client, owner)

    r = await client.patch(f"/api/assets/{asset.id}", json={"title": "Renamed"})
    assert r.status_code == 200, r.text

    await _assert_content_untouched(session, asset, owner.id)


@pytest.mark.asyncio
async def test_project_move_does_not_change_content_timestamp(client, session):
    owner = await mk_user(session)
    project = Project(slug=generate_slug(), name="P", created_by=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(project_id=project.id, user_id=owner.id, role="owner", accepted_at=PAST)
    )
    asset = await _aged_asset(session, owner)
    await login_as(client, owner)

    r = await client.patch(
        f"/api/assets/by-slug/{asset.slug}/project", json={"project_id": str(project.id)}
    )
    assert r.status_code == 200, r.text

    await _assert_content_untouched(session, asset, owner.id)


@pytest.mark.asyncio
async def test_outline_worker_does_not_change_content_timestamp(session, fs_storage, monkeypatch):
    monkeypatch.setattr(
        outline_mod, "SessionLocal", async_sessionmaker(session.bind, expire_on_commit=False)
    )
    owner = await mk_user(session)
    asset = await _aged_asset(session, owner)
    await put_blob(asset, "doc.md", b"# Heading\n\nBody.")

    result = await outline_mod.rebuild_outline({}, str(asset.id))
    assert "error" not in result, result

    await _assert_content_untouched(session, asset, owner.id)
    assert asset.outline_status == "fresh"


@pytest.mark.asyncio
async def test_scanner_status_change_does_not_change_content_timestamp(session, fs_storage):
    owner = await mk_user(session)
    asset = await _aged_asset(session, owner, kind="html_bundle", entry_path="index.html")
    await put_blob(asset, "index.html", b'<!doctype html><script src="app.js"></script>')
    await put_blob(asset, "app.js", b'eval("1 + 1");')

    await asset_security.scan_and_apply(asset, get_settings(), session)
    await session.commit()

    await _assert_content_untouched(session, asset, owner.id)
    assert asset.security_status == "critical"


@pytest.mark.asyncio
async def test_admin_bypass_does_not_change_content_timestamp(client, session):
    owner = await mk_user(session)
    admin = await mk_admin(session)
    asset = await _aged_asset(
        session, owner, kind="html_bundle", entry_path="index.html", security_status="critical"
    )
    await login_as(client, admin)

    r = await client.post(
        f"/api/admin/assets/{asset.id}/security-bypass", json={"reason": "reviewed, fine"}
    )
    assert r.status_code == 200, r.text

    await _assert_content_untouched(session, asset, owner.id)


# ---------- a new version records the time and the actor ----------


@pytest.mark.asyncio
async def test_new_version_sets_content_fields_to_the_actor(client, session, fs_storage):
    owner = await mk_user(session)
    editor = await mk_user(session)
    asset = await _aged_asset(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=editor.id, role="editor"))
    await session.commit()
    await put_blob(asset, "doc.md", b"# Old")
    await login_as(client, editor)

    before = datetime.now(UTC)
    r = await client.put(f"/api/assets/{asset.id}/content", json={"content": "# New"})
    assert r.status_code == 201, r.text

    await session.refresh(asset)
    assert asset.version == 2
    assert asset.content_updated_at is not None and asset.content_updated_at >= before
    assert asset.content_updated_by == editor.id


@pytest.mark.asyncio
async def test_content_fields_are_exposed_in_index_meta_and_summary(client, session):
    owner = await mk_user(session)
    asset = await _aged_asset(session, owner)
    await login_as(client, owner)
    index = (await client.get("/api/assets/index")).json()["items"]
    meta = (await client.get(f"/api/assets/by-slug/{asset.slug}/meta")).json()
    listing = (await client.get("/api/assets")).json()["items"]
    search = (await client.get("/api/assets/search?q=Test")).json()

    for rows in (index, [meta], listing, search):
        row = next(i for i in rows if i["id"] == str(asset.id))
        assert datetime.fromisoformat(row["content_updated_at"]) == PAST
        assert row["content_updated_by"] == str(owner.id)


# ---------- every v1 creation path sets both fields ----------


async def _md(client):
    return await client.post("/api/assets", files={"file": ("note.md", b"# Note", "text/markdown")})


async def _collection(client):
    return await client.post(
        "/api/assets/collection",
        files=[("files", ("index.md", b"# Index", "text/markdown"))],
        data={"paths": ["index.md"]},
    )


async def _html(client):
    return await client.post(
        "/api/assets/html",
        files=[("files", ("index.html", b"<!doctype html><p>hi</p>", "text/html"))],
        data={"paths": ["index.html"]},
    )


async def _pdf(client):
    return await client.post("/api/assets/pdf", files=pdf_file("r.pdf", make_pdf(["Page"])))


async def _document(client):
    data = make_docx([("h1", "Brief"), ("p", "Body")])
    return await client.post("/api/assets/document", files=office_file("b.docx", data))


async def _html_json(client):
    return await client.post(
        "/api/assets/html-json",
        json={
            "title": "Bundle",
            "entry_path": "index.html",
            "files": [{"path": "index.html", "content_text": "<!doctype html><p>hi</p>"}],
        },
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "upload",
    [_md, _collection, _html, _pdf, _document, _html_json],
    ids=["md", "collection", "html", "pdf", "document", "html-json"],
)
async def test_every_v1_path_sets_content_fields(client, session, fs_storage, no_jobs, upload):
    owner = await mk_user(session)
    await session.commit()
    await login_as(client, owner)

    before = datetime.now(UTC)
    r = await upload(client)
    assert r.status_code == 201, r.text

    asset = await session.scalar(select(Asset).where(Asset.slug == r.json()["slug"]))
    assert asset is not None
    await session.refresh(asset)
    assert asset.version == 1
    assert asset.content_updated_at is not None and asset.content_updated_at >= before
    assert asset.content_updated_by == owner.id
