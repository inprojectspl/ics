"""MCP outline and content read carry freshness (ADR-0015) and, for readers
with graph access, the outgoing relations with their anchors (ADR-0016)."""

from __future__ import annotations

import pytest

from app.models import AssetRelation, AssetShare
from tests.conftest import login_as, mk_asset, mk_user, put_blob


async def _with_outline(session, owner, title):
    asset = await mk_asset(session, owner, title=title)
    asset.outline_status = "fresh"
    asset.outline_version = asset.version
    asset.outline_json = {"items": [{"title": "Scope", "level": 1}]}
    return asset


def _edge(source, target, relation_type, owner, **kw):
    return AssetRelation(
        source_asset_id=source.id,
        target_asset_id=target.id,
        relation_type=relation_type,
        target_version=1,
        origin="manual",
        created_by=owner.id,
        **kw,
    )


@pytest.mark.asyncio
async def test_superseded_outline_names_successor_and_edges(client, session, fs_storage):
    owner = await mk_user(session)
    old = await _with_outline(session, owner, "Spec v1")
    new = await mk_asset(session, owner, title="Spec v2")
    arch = await mk_asset(session, owner, title="Architecture")
    old.summary = "Booking API, first draft."
    session.add_all(
        [
            _edge(new, old, "supersedes", owner),
            _edge(old, arch, "depends_on", owner, target_anchor="data-layer"),
        ]
    )
    await session.commit()
    await login_as(client, owner)

    body = (await client.get(f"/api/assets/by-slug/{old.slug}/outline")).json()
    assert body["items"] == [{"title": "Scope", "level": 1}]
    assert body["summary"] == "Booking API, first draft."
    assert body["freshness"] == "superseded"
    assert body["superseded_by"] == {"id": str(new.id), "slug": new.slug, "title": "Spec v2"}
    (edge,) = body["edges"]
    assert edge["relation_type"] == "depends_on"
    assert edge["target_slug"] == arch.slug
    assert edge["target_anchor"] == "data-layer"


@pytest.mark.asyncio
async def test_viewer_without_graph_access_gets_outline_without_edges(client, session, fs_storage):
    owner = await mk_user(session)
    reader = await mk_user(session)
    doc = await _with_outline(session, owner, "Design")
    target = await mk_asset(session, owner, title="Goals")
    session.add_all(
        [
            _edge(doc, target, "derived_from", owner),
            AssetShare(asset_id=doc.id, user_id=reader.id, role="viewer"),
            AssetShare(asset_id=target.id, user_id=reader.id, role="viewer"),
        ]
    )
    await session.commit()
    await login_as(client, reader)

    r = await client.get(f"/api/assets/by-slug/{doc.slug}/outline")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == [{"title": "Scope", "level": 1}]
    assert body["freshness"] == "current"
    assert "edges" not in body
    assert target.slug not in r.text


@pytest.mark.asyncio
async def test_content_read_reports_freshness(client, session, fs_storage):
    owner = await mk_user(session)
    old = await mk_asset(session, owner, title="Old")
    new = await mk_asset(session, owner, title="New")
    session.add(_edge(new, old, "supersedes", owner))
    await session.commit()
    await put_blob(old, "doc.md", b"# Old\nbody\n")
    await put_blob(new, "doc.md", b"# New\nbody\n")
    await login_as(client, owner)

    r = await client.get(f"/api/assets/by-slug/{old.slug}/file-mcp")
    assert r.status_code == 200, r.text
    assert r.json()["content"].startswith("# Old")
    assert r.json()["freshness"] == "superseded"
    assert r.json()["superseded_by"]["slug"] == new.slug

    body = (await client.get(f"/api/assets/by-slug/{new.slug}/file-mcp")).json()
    assert body["freshness"] == "current"
    assert body["superseded_by"] is None
