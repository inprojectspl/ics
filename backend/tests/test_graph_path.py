"""Path search for the graph explorer (POST /api/assets/by-slug/{slug}/path):
the shortest walk from what is on screen, only through documents the reader
may expand, from a document or from a project of theirs."""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise

from app.models import AssetRelation, AssetShare, Project, ProjectMember
from app.services.graph_path import MAX_PATH_DEPTH, find_path
from app.services.relations import RELATION_TYPE_SET
from app.slug import generate_slug
from tests.conftest import login_as, mk_admin, mk_asset, mk_user


def _rel(source, target, relation_type="depends_on") -> AssetRelation:
    return AssetRelation(
        source_asset_id=source.id,
        target_asset_id=target.id,
        relation_type=relation_type,
        origin="manual",
    )


async def _project(session, owner) -> Project:
    project = Project(slug=generate_slug(), name="Walk", created_by=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(
            project_id=project.id, user_id=owner.id, role="owner", accepted_at=datetime.now(UTC)
        )
    )
    await session.flush()
    return project


def _slugs(path) -> list[str]:
    return [step["slug"] for step in path]


async def test_shortest_walk_follows_edges_either_way(session):
    owner = await mk_user(session)
    a, b, c, d, e = [await mk_asset(session, owner) for _ in range(5)]
    # a -> b <- c -> d, plus a longer detour a -> e ... (e is a dead end).
    session.add_all([_rel(a, b), _rel(c, b, "references"), _rel(c, d), _rel(a, e)])
    await session.commit()

    path = await find_path(session, owner, d, starts=[a.id], projects=[], types=RELATION_TYPE_SET)
    assert path is not None
    assert _slugs(path) == [a.slug, b.slug, c.slug, d.slug]
    assert {step["kind"] for step in path} == {"doc"}

    # A type left out of the filter is not a way through.
    assert (
        await find_path(session, owner, d, starts=[a.id], projects=[], types={"depends_on"}) is None
    )


async def test_no_walk_through_a_document_the_reader_cannot_expand(session):
    actor = await mk_user(session)
    other = await mk_user(session)
    a = await mk_asset(session, actor)
    hidden = await mk_asset(session, other)
    viewer_only = await mk_asset(session, other)
    target = await mk_asset(session, actor)
    session.add(AssetShare(asset_id=viewer_only.id, user_id=actor.id, role="viewer"))
    session.add_all([_rel(a, hidden), _rel(hidden, target)])
    session.add_all([_rel(a, viewer_only), _rel(viewer_only, target)])
    await session.commit()

    assert (
        await find_path(session, actor, target, starts=[a.id], projects=[], types=RELATION_TYPE_SET)
        is None
    )
    # A document the reader may only view is fine as the destination.
    path = await find_path(
        session, actor, viewer_only, starts=[a.id], projects=[], types=RELATION_TYPE_SET
    )
    assert path is not None
    assert _slugs(path) == [a.slug, viewer_only.slug]


async def test_walk_from_a_project_holding_a_document_on_the_way(session):
    owner = await mk_user(session)
    project = await _project(session, owner)
    member = await mk_asset(session, owner)
    member.project_id = project.id
    outside = await mk_asset(session, owner)
    session.add(_rel(outside, member, "references"))
    await session.commit()

    path = await find_path(
        session, owner, outside, starts=[], projects=[project], types=RELATION_TYPE_SET
    )
    assert path is not None
    assert [s["kind"] for s in path] == ["project", "doc", "doc"]
    assert _slugs(path) == [project.slug, member.slug, outside.slug]

    direct = await find_path(
        session, owner, member, starts=[], projects=[project], types=RELATION_TYPE_SET
    )
    assert direct is not None
    assert _slugs(direct) == [project.slug, member.slug]


async def test_search_stops_at_the_depth_limit(session):
    owner = await mk_user(session)
    chain = [await mk_asset(session, owner) for _ in range(MAX_PATH_DEPTH + 2)]
    session.add_all([_rel(x, y) for x, y in pairwise(chain)])
    await session.commit()

    near = await find_path(
        session,
        owner,
        chain[MAX_PATH_DEPTH],
        starts=[chain[0].id],
        projects=[],
        types=RELATION_TYPE_SET,
    )
    assert near is not None
    assert len(near) == MAX_PATH_DEPTH + 1
    far = await find_path(
        session, owner, chain[-1], starts=[chain[0].id], projects=[], types=RELATION_TYPE_SET
    )
    assert far is None


async def test_route_hides_unreadable_targets_and_foreign_projects(client, session):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    project = await _project(session, owner)
    member = await mk_asset(session, owner)
    member.project_id = project.id
    target = await mk_asset(session, stranger)
    session.add(AssetShare(asset_id=target.id, user_id=owner.id, role="viewer"))
    session.add(_rel(member, target))
    secret = await mk_asset(session, stranger)
    await session.commit()

    await login_as(client, owner)
    r = await client.post(
        f"/api/assets/by-slug/{target.slug}/path", json={"projects": [project.slug]}
    )
    assert r.status_code == 200
    assert _slugs(r.json()["path"]) == [project.slug, member.slug, target.slug]

    r = await client.post(
        f"/api/assets/by-slug/{secret.slug}/path", json={"from": [str(member.id)]}
    )
    assert r.status_code == 404
    assert r.json()["code"] == "asset_not_found"

    r = await client.post(f"/api/assets/by-slug/{target.slug}/path", json={"types": ["nonsense"]})
    assert r.status_code == 400
    assert r.json()["code"] == "relation_type_invalid"

    # The stranger is no member: the project is ignored, so there is no way in.
    await login_as(client, stranger)
    r = await client.post(
        f"/api/assets/by-slug/{target.slug}/path", json={"projects": [project.slug]}
    )
    assert r.status_code == 200
    assert r.json()["path"] is None

    # An admin walks from any project.
    admin = await mk_admin(session)
    await login_as(client, admin)
    r = await client.post(
        f"/api/assets/by-slug/{target.slug}/path", json={"projects": [project.slug]}
    )
    assert _slugs(r.json()["path"]) == [project.slug, member.slug, target.slug]
