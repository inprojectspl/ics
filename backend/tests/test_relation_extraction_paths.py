"""Relations extracted on every content write (ADR-0016, section 4): each v1
creation path, new versions and GitLab sync replace the source's `extracted`
edges; only targets the author can see get one; manual edges stay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import delete, select

from app import signing
from app.models import Asset, AssetRelation, User
from tests.conftest import login_as, make_tar_gz, mk_asset, mk_user
from tests.office_factory import make_docx, office_file
from tests.pdf_factory import make_pdf, pdf_file


async def _md(client, _session, _user, text: str) -> str:
    r = await client.post(
        "/api/assets", files={"file": ("note.md", text.encode(), "text/markdown")}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _collection(client, _session, _user, text: str) -> str:
    r = await client.post(
        "/api/assets/collection",
        files=[("files", ("index.md", text.encode(), "text/markdown"))],
        data={"paths": ["index.md"]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _html(text: str) -> str:
    return f"<!doctype html><html><body><p>{text}</p></body></html>"


async def _html_multipart(client, _session, _user, text: str) -> str:
    r = await client.post(
        "/api/assets/html",
        files=[("files", ("index.html", _html(text).encode(), "text/html"))],
        data={"paths": ["index.html"]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _html_json(client, _session, _user, text: str) -> str:
    r = await client.post(
        "/api/assets/html-json",
        json={
            "title": "Bundle",
            "entry_path": "index.html",
            "files": [{"path": "index.html", "content_text": _html(text)}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _pdf(client, _session, _user, text: str) -> str:
    r = await client.post("/api/assets/pdf", files=pdf_file("report.pdf", make_pdf([text])))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _document(client, _session, _user, text: str) -> str:
    r = await client.post(
        "/api/assets/document", files=office_file("spec.docx", make_docx([("p", text)]))
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _gitlab_sync(client, session, user, text: str) -> str:
    """The binding's creator is the author of synced content."""
    asset = await mk_asset(session, user, kind="md_collection", entry_path="README.md")
    await session.commit()
    r = await client.post("/api/bindings", json={"asset_id": str(asset.id)})
    assert r.status_code == 201, r.text
    binding_id, key = r.json()["id"], r.json()["private_key"]
    bundle = make_tar_gz({"README.md": text.encode()})
    manifest = json.dumps(
        {
            "binding_id": binding_id,
            "commit_sha": "cafe1234",
            "commit_timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        }
    ).encode()
    await client.post("/api/auth/logout")
    r = await client.post(
        f"/api/bindings/{binding_id}/sync",
        files={
            "manifest": ("m.json", manifest, "application/json"),
            "signature": ("s.b64", signing.sign(manifest, key).encode(), "text/plain"),
            "bundle": ("b.tar.gz", bundle, "application/gzip"),
        },
    )
    assert r.status_code == 201, r.text
    await login_as(client, user)
    return str(asset.id)


async def _empty_file(client, session, user, text: str) -> str:
    """Adding an empty file is a new version: extraction runs again, so an
    edge removed behind its back comes back."""
    asset_id = await _collection(client, session, user, text)
    await session.execute(delete(AssetRelation).where(AssetRelation.source_asset_id == asset_id))
    await session.commit()
    r = await client.post(f"/api/assets/{asset_id}/files/empty", json={"path": "new.md"})
    assert r.status_code == 201, r.text
    return asset_id


Creator = Callable[..., Awaitable[str]]
CREATORS: dict[str, Creator] = {
    "md": _md,
    "collection": _collection,
    "html": _html_multipart,
    "html_json": _html_json,
    "pdf": _pdf,
    "document": _document,
    "gitlab_sync": _gitlab_sync,
    "empty_file": _empty_file,
}


async def _edges(session, source_id) -> list[AssetRelation]:
    rows = await session.scalars(
        select(AssetRelation)
        .where(AssetRelation.source_asset_id == UUID(str(source_id)))
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


async def _author_and_target(client, session) -> tuple[User, Asset]:
    author = await mk_user(session)
    target = await mk_asset(session, author, title="Target")
    await session.commit()
    await login_as(client, author)
    return author, target


@pytest.mark.asyncio
@pytest.mark.parametrize("path", list(CREATORS))
async def test_every_write_path_extracts_wikilink(client, session, fs_storage, path):
    author, target = await _author_and_target(client, session)
    source_id = await CREATORS[path](client, session, author, f"See [[ics:{target.slug}]] now.")

    (edge,) = await _edges(session, source_id)
    assert edge.target_asset_id == target.id
    assert edge.relation_type == "references"
    assert edge.origin == "extracted"
    assert edge.created_by == author.id
    assert edge.target_version == target.version


@pytest.mark.asyncio
async def test_share_token_link_resolves_to_its_asset(client, session, fs_storage):
    author, target = await _author_and_target(client, session)
    r = await client.post(f"/api/assets/{target.id}/shares", json={"mode": "org_sso"})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    source_id = await _md(client, session, author, f"Link: http://ics.localhost/s/{token}\n")

    (edge,) = await _edges(session, source_id)
    assert edge.target_asset_id == target.id


@pytest.mark.asyncio
async def test_link_to_invisible_document_is_recorded_but_not_shown(client, session, fs_storage):
    """The edge is a fact about the text, so it exists whoever wrote it; the
    author, who cannot open the target, does not see it."""
    author, target = await _author_and_target(client, session)
    stranger = await mk_user(session)
    hidden = await mk_asset(session, stranger, title="Hidden")
    await session.commit()
    text = f"[[ics:{hidden.slug}]] and [[ics:{target.slug}]]\n"
    source_id = await _md(client, session, author, text)

    edges = await _edges(session, source_id)
    assert {e.target_asset_id for e in edges} == {hidden.id, target.id}
    r = await client.get(f"/api/assets/{source_id}")
    r = await client.get(f"/api/assets/by-slug/{r.json()['slug']}/relations")
    assert r.status_code == 200, r.text
    assert hidden.slug not in r.text
    assert str(hidden.id) not in r.text


@pytest.mark.asyncio
async def test_new_version_replaces_extracted_edges_but_keeps_manual(client, session, fs_storage):
    author, linked = await _author_and_target(client, session)
    manual_target = await mk_asset(session, author, title="Manual")
    await session.commit()
    source_id = await _md(client, session, author, f"[[ics:{linked.slug}]]\n")
    r = await client.post(
        f"/api/assets/{source_id}/relations",
        json={"relation_type": "depends_on", "target_id": str(manual_target.id)},
    )
    assert r.status_code == 201, r.text
    assert len(await _edges(session, source_id)) == 2

    r = await client.put(f"/api/assets/{source_id}/content", json={"content": "No links.\n"})
    assert r.status_code == 201, r.text

    (edge,) = await _edges(session, source_id)
    assert edge.target_asset_id == manual_target.id
    assert edge.origin == "manual"


@pytest.mark.asyncio
async def test_link_added_in_new_version_creates_references_edge(client, session, fs_storage):
    author, target = await _author_and_target(client, session)
    source_id = await _md(client, session, author, "No links yet.\n")
    assert await _edges(session, source_id) == []

    r = await client.put(
        f"/api/assets/{source_id}/content", json={"content": f"Now see [[ics:{target.slug}]].\n"}
    )
    assert r.status_code == 201, r.text

    (edge,) = await _edges(session, source_id)
    assert edge.target_asset_id == target.id
    assert edge.relation_type == "references"
    assert edge.origin == "extracted"


@pytest.mark.asyncio
async def test_unchanged_link_keeps_its_edge_and_refreshes_target_version(
    client, session, fs_storage
):
    """Only the difference is written: an edge whose link is still in the text
    survives a new version (same row) and records the target's current
    version, while a link that disappeared loses its edge."""
    author, kept_target = await _author_and_target(client, session)
    dropped_target = await mk_asset(session, author, title="Dropped")
    await session.commit()
    source_id = await _md(
        client, session, author, f"[[ics:{kept_target.slug}]] [[ics:{dropped_target.slug}]]\n"
    )
    before = {e.target_asset_id: e.id for e in await _edges(session, source_id)}
    assert set(before) == {kept_target.id, dropped_target.id}

    kept_target.version = 5
    await session.commit()
    r = await client.put(
        f"/api/assets/{source_id}/content", json={"content": f"[[ics:{kept_target.slug}]] v2\n"}
    )
    assert r.status_code == 201, r.text

    (edge,) = await _edges(session, source_id)
    assert edge.id == before[kept_target.id]
    assert edge.target_version == 5
