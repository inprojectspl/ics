"""Neighbourhood BFS (ADR-0016, section 6): access checked per level, a bounded
number of edge queries, and termination on cycles."""

from __future__ import annotations

import pytest
from sqlalchemy import event

from app.models import Asset, AssetRelation, AssetShare
from app.services.relation_graph import neighbourhood
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_user


def _rel(source, target, relation_type="depends_on") -> AssetRelation:
    return AssetRelation(
        source_asset_id=source.id,
        target_asset_id=target.id,
        relation_type=relation_type,
        origin="manual",
    )


def _slugs(result) -> set[str]:
    return {n["slug"] for n in result["nodes"]}


@pytest.mark.asyncio
async def test_path_through_invisible_node_does_not_exist(session):
    actor = await mk_user(session)
    other = await mk_user(session)
    a = await mk_asset(session, actor)
    b = await mk_asset(session, other)
    c = await mk_asset(session, actor)
    session.add_all([_rel(a, b), _rel(b, c)])
    await session.commit()

    result = await neighbourhood(session, actor, a, depth=3)
    assert _slugs(result) == {a.slug}
    assert result["edges"] == []


@pytest.mark.asyncio
async def test_visible_node_without_graph_access_is_a_leaf(session):
    actor = await mk_user(session)
    other = await mk_user(session)
    a = await mk_asset(session, actor)
    b = await mk_asset(session, other)
    c = await mk_asset(session, other)
    session.add(AssetShare(asset_id=b.id, user_id=actor.id, role="viewer"))
    session.add(AssetShare(asset_id=c.id, user_id=actor.id, role="viewer"))
    session.add_all([_rel(a, b), _rel(b, c)])
    await session.commit()

    result = await neighbourhood(session, actor, a, depth=3)
    assert _slugs(result) == {a.slug, b.slug}
    nodes = {n["slug"]: n for n in result["nodes"]}
    assert nodes[b.slug]["expandable"] is False
    assert nodes[b.slug]["depth"] == 1
    assert [(e["source_id"], e["target_id"]) for e in result["edges"]] == [(str(a.id), str(b.id))]


@pytest.mark.asyncio
async def test_cycle_terminates(session):
    owner = await mk_user(session)
    a, b, c = [await mk_asset(session, owner) for _ in range(3)]
    session.add_all([_rel(a, b), _rel(b, c), _rel(c, a)])
    await session.commit()

    result = await neighbourhood(session, owner, a, depth=3)
    assert _slugs(result) == {a.slug, b.slug, c.slug}
    assert len(result["edges"]) == 3
    assert result["truncated"] is False


@pytest.mark.asyncio
async def test_references_only_on_request(session):
    owner = await mk_user(session)
    a, b, c = [await mk_asset(session, owner) for _ in range(3)]
    session.add_all([_rel(a, b, "references"), _rel(c, a, "supersedes")])
    await session.commit()

    assert _slugs(await neighbourhood(session, owner, a)) == {a.slug, c.slug}
    assert _slugs(await neighbourhood(session, owner, a, types=["references"])) == {
        a.slug,
        b.slug,
    }
    nodes = {n["slug"]: n for n in (await neighbourhood(session, owner, a))["nodes"]}
    assert nodes[a.slug]["freshness"] == "superseded"


@pytest.mark.asyncio
async def test_large_graph_is_bounded_in_queries_and_nodes(session):
    """A 1000-node tree (fan-out 10): depth 3 with max_nodes 200 touches the
    edge table in at most 6 statements and cuts the result at 200 nodes,
    nearer levels first."""
    owner = await mk_user(session)
    assets = [
        Asset(
            slug=generate_slug(),
            owner_id=owner.id,
            kind="md_single",
            title=f"n{i}",
            storage_prefix=generate_slug(8),
            entry_path="doc.md",
            security_status="clean",
            version=1,
        )
        for i in range(1000)
    ]
    session.add_all(assets)
    await session.flush()
    session.add_all(
        _rel(assets[i], assets[child])
        for i in range(100)
        for child in range(10 * i + 1, min(10 * i + 11, 1000))
    )
    await session.commit()

    statements: list[str] = []

    def _count(_conn, _cursor, statement, *_args):
        if "asset_relations" in statement:
            statements.append(statement)

    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _count)
    try:
        result = await neighbourhood(session, owner, assets[0], depth=3, max_nodes=200)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert len(statements) <= 6, statements
    assert len(result["nodes"]) == 200
    assert result["truncated"] is True
    depths = [n["depth"] for n in result["nodes"]]
    assert depths.count(1) == 10
    assert depths.count(2) == 100
    assert depths.count(3) == 89


@pytest.mark.asyncio
async def test_endpoint_requires_graph_access(client, session):
    owner = await mk_user(session)
    share_viewer = await mk_user(session)
    a = await mk_asset(session, owner)
    b = await mk_asset(session, owner)
    session.add(AssetShare(asset_id=a.id, user_id=share_viewer.id, role="viewer"))
    session.add(_rel(a, b))
    await session.commit()

    await login_as(client, owner)
    r = await client.get(f"/api/assets/by-slug/{a.slug}/neighbourhood?depth=2")
    assert r.status_code == 200
    assert {n["slug"] for n in r.json()["nodes"]} == {a.slug, b.slug}
    r = await client.get(f"/api/assets/by-slug/{a.slug}/neighbourhood?depth=4")
    assert r.status_code == 422

    await login_as(client, share_viewer)
    r = await client.get(f"/api/assets/by-slug/{a.slug}/neighbourhood")
    assert r.status_code == 404
    assert r.json()["code"] == "asset_not_found"
