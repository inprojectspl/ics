"""Duplicate suggestions in project hygiene: certain duplicates by content
hash, candidates by similar title and the same doc type, dismissals that
stick, and no edge without a user action."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models import AssetRelation, DuplicateDismissal, Project, ProjectMember
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_doc_type, mk_user


async def _project(session, owner, *members) -> Project:
    project = Project(slug=generate_slug(), name="Dups", created_by=owner.id)
    session.add(project)
    await session.flush()
    now = datetime.now(UTC)
    session.add_all(
        ProjectMember(project_id=project.id, user_id=u.id, role=role, accepted_at=now)
        for u, role in [(owner, "owner"), *members]
    )
    await session.flush()
    return project


async def _doc(session, owner, project, title, content, doc_type=None):
    asset = await mk_asset(session, owner, title=title)
    asset.project_id = project.id
    asset.search_content = content
    asset.doc_type = doc_type
    return asset


async def _pairs(client, project) -> tuple[list[dict], dict]:
    r = await client.get(f"/api/projects/{project.slug}/hygiene?list=duplicates")
    assert r.status_code == 200, r.text
    body = r.json()
    return body["items"], body["counters"]


def _pair_ids(item) -> frozenset[str]:
    return frozenset({item["a"]["id"], item["b"]["id"]})


async def _edge_count(session) -> int:
    return int(await session.scalar(select(func.count()).select_from(AssetRelation)) or 0)


async def test_same_content_is_a_certain_duplicate(client, session):
    owner = await mk_user(session)
    project = await _project(session, owner)
    a = await _doc(session, owner, project, "Deployment guide", "Run   make deploy.\nDone")
    b = await _doc(session, owner, project, "Release notes", "run make DEPLOY. done")
    await _doc(session, owner, project, "Unrelated", "Something else entirely")
    await session.commit()

    await login_as(client, owner)
    items, counters = await _pairs(client, project)
    assert [(_pair_ids(i), i["certainty"]) for i in items] == [
        (frozenset({str(a.id), str(b.id)}), "certain")
    ]
    assert counters["duplicates"] == 1


async def test_similar_titles_need_the_same_doc_type(client, session):
    owner = await mk_user(session)
    project = await _project(session, owner)
    spec, other = await mk_doc_type(session), await mk_doc_type(session)
    a = await _doc(session, owner, project, "Payment API spec", "one", spec.key)
    b = await _doc(session, owner, project, "Payment API spec v2", "two", spec.key)
    await _doc(session, owner, project, "Payment API specs", "three", other.key)
    await session.commit()

    await login_as(client, owner)
    items, _ = await _pairs(client, project)
    assert [(_pair_ids(i), i["certainty"]) for i in items] == [
        (frozenset({str(a.id), str(b.id)}), "candidate")
    ]
    assert items[0]["similarity"] > 0.6


async def test_listing_creates_no_edges(client, session):
    owner = await mk_user(session)
    project = await _project(session, owner)
    await _doc(session, owner, project, "A", "same text")
    await _doc(session, owner, project, "B", "same text")
    await session.commit()
    before = await _edge_count(session)

    await login_as(client, owner)
    items, _ = await _pairs(client, project)
    assert len(items) == 1
    await _pairs(client, project)
    assert await _edge_count(session) == before


async def test_dismissed_pair_is_not_listed_again(client, session):
    owner = await mk_user(session)
    project = await _project(session, owner)
    a = await _doc(session, owner, project, "A", "same text")
    b = await _doc(session, owner, project, "B", "same text")
    await session.commit()
    await login_as(client, owner)

    url = f"/api/projects/{project.slug}/hygiene/duplicates/dismiss"
    r = await client.post(url, json={"source_id": str(b.id), "target_id": str(a.id)})
    assert r.status_code == 204, r.text
    # Idempotent.
    r = await client.post(url, json={"source_id": str(a.id), "target_id": str(b.id)})
    assert r.status_code == 204, r.text

    items, counters = await _pairs(client, project)
    assert items == []
    assert counters["duplicates"] == 0
    rows = (await session.scalars(select(DuplicateDismissal))).all()
    assert [(d.asset_a_id, d.asset_b_id) for d in rows if d.dismissed_by == owner.id] == [
        tuple(sorted((a.id, b.id)))
    ]
    # A dismissal never adds an edge.
    linked = await session.scalar(
        select(func.count())
        .select_from(AssetRelation)
        .where(AssetRelation.source_asset_id.in_([a.id, b.id]))
    )
    assert linked == 0


async def test_mark_creates_a_duplicates_relation_and_drops_the_suggestion(client, session):
    owner = await mk_user(session)
    project = await _project(session, owner)
    a = await _doc(session, owner, project, "A", "same text")
    b = await _doc(session, owner, project, "B", "same text")
    await session.commit()
    await login_as(client, owner)

    r = await client.post(
        f"/api/projects/{project.slug}/hygiene/duplicates/mark",
        json={"source_id": str(b.id), "target_id": str(a.id)},
    )
    assert r.status_code == 201, r.text
    edge = await session.scalar(select(AssetRelation).where(AssetRelation.source_asset_id == b.id))
    assert edge is not None
    assert (edge.target_asset_id, edge.relation_type, edge.origin) == (
        a.id,
        "duplicates",
        "manual",
    )
    items, _ = await _pairs(client, project)
    assert items == []


async def test_actions_refuse_documents_outside_the_project_and_viewers(client, session):
    owner = await mk_user(session)
    viewer = await mk_user(session)
    project = await _project(session, owner, (viewer, "viewer"))
    a = await _doc(session, owner, project, "A", "same text")
    outside = await mk_asset(session, owner, title="Outside")
    await session.commit()
    body = {"source_id": str(a.id), "target_id": str(outside.id)}

    await login_as(client, owner)
    for action in ("mark", "dismiss"):
        r = await client.post(
            f"/api/projects/{project.slug}/hygiene/duplicates/{action}", json=body
        )
        assert r.status_code == 404
        assert r.json()["code"] == "asset_not_found"

    await login_as(client, viewer)
    r = await client.post(f"/api/projects/{project.slug}/hygiene/duplicates/dismiss", json=body)
    assert r.status_code == 404
    assert r.json()["code"] == "project_not_found"
