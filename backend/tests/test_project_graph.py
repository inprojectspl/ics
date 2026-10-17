"""Project document graph (GET /api/projects/{slug}/graph): member-only access,
no trace of documents the caller cannot see, and a statement count that does
not grow with the project."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import event

from app.models import (
    Asset,
    AssetExternalRef,
    AssetProjectShare,
    AssetRelation,
    AssetShare,
    Project,
    ProjectMember,
)
from app.slug import generate_slug
from tests.conftest import login_as, mk_admin, mk_asset, mk_user


def _rel(source, target, relation_type="depends_on") -> AssetRelation:
    return AssetRelation(
        source_asset_id=source.id,
        target_asset_id=target.id,
        relation_type=relation_type,
        origin="manual",
    )


async def _project(session, owner, *members: tuple) -> Project:
    project = Project(slug=generate_slug(), name="Graph", created_by=owner.id)
    session.add(project)
    await session.flush()
    now = datetime.now(UTC)
    session.add(
        ProjectMember(project_id=project.id, user_id=owner.id, role="owner", accepted_at=now)
    )
    for user, role in members:
        session.add(
            ProjectMember(project_id=project.id, user_id=user.id, role=role, accepted_at=now)
        )
    await session.flush()
    return project


async def _doc(session, owner, project, title="Doc") -> Asset:
    asset = await mk_asset(session, owner, title=title)
    asset.project_id = project.id
    return asset


async def test_non_member_gets_404_member_and_admin_get_the_graph(client, session):
    owner = await mk_user(session)
    viewer = await mk_user(session)
    stranger = await mk_user(session)
    admin = await mk_admin(session)
    project = await _project(session, owner, (viewer, "viewer"))
    await _doc(session, owner, project)
    await session.commit()

    await login_as(client, stranger)
    assert (await client.get(f"/api/projects/{project.slug}/graph")).status_code == 404
    assert (await client.get("/api/projects/nope-nope/graph")).status_code == 404
    for user in (viewer, admin):
        await login_as(client, user)
        r = await client.get(f"/api/projects/{project.slug}/graph")
        assert r.status_code == 200, r.text
        assert len(r.json()["nodes"]) == 1


async def test_nodes_edges_and_external_documents(client, session):
    owner = await mk_user(session)
    viewer = await mk_user(session)
    outsider = await mk_user(session)
    project = await _project(session, owner, (viewer, "viewer"))
    a = await _doc(session, owner, project, "A")
    b = await _doc(session, owner, project, "B")
    lonely = await _doc(session, owner, project, "Lonely")
    # Assigned from another owner's space: part of the project, not external.
    assigned = await mk_asset(session, outsider, title="Assigned")
    session.add(AssetProjectShare(asset_id=assigned.id, project_id=project.id, role="viewer"))
    # Outside, readable by the viewer through a direct share.
    public = await mk_asset(session, outsider, title="Visible outside")
    session.add(AssetShare(asset_id=public.id, user_id=viewer.id, role="viewer"))
    # Outside and invisible to the viewer.
    hidden = await mk_asset(session, outsider, title="Secret outside")
    session.add_all(
        [
            _rel(a, b),
            _rel(b, public, "references"),
            _rel(assigned, a, "derived_from"),
            _rel(lonely, hidden, "supersedes"),
            _rel(hidden, lonely, "references"),
        ]
    )
    await session.commit()

    await login_as(client, viewer)
    r = await client.get(f"/api/projects/{project.slug}/graph")
    assert r.status_code == 200, r.text
    body = r.json()
    nodes = {n["slug"]: n for n in body["nodes"]}

    assert set(nodes) == {a.slug, b.slug, lonely.slug, assigned.slug, public.slug}
    assert hidden.slug not in r.text and "Secret outside" not in r.text
    ends = {e["source_id"] for e in body["edges"]} | {e["target_id"] for e in body["edges"]}
    assert str(hidden.id) not in ends
    assert len(body["edges"]) == 3

    assert nodes[public.slug]["external"] is True
    assert not any(nodes[s]["external"] for s in (a.slug, b.slug, lonely.slug, assigned.slug))
    assert body["truncated"] is False
    assert {"doc_type", "freshness", "summary", "content_updated_at"} <= set(nodes[a.slug])
    assert "tasks" not in body


async def test_task_layer_on_request(client, session):
    owner = await mk_user(session)
    project = await _project(session, owner)
    a = await _doc(session, owner, project)
    session.add(
        AssetExternalRef(
            asset_id=a.id,
            system="openproject",
            entity="work_package",
            external_id="123",
            role="deliverable",
            label="Ship it",
            origin="manual",
        )
    )
    await session.commit()

    await login_as(client, owner)
    body = (await client.get(f"/api/projects/{project.slug}/graph?include=tasks")).json()
    assert [t["id"] for t in body["tasks"]] == ["openproject:work_package:123"]
    assert body["task_links"] == [
        {
            "task_id": "openproject:work_package:123",
            "asset_id": str(a.id),
            "role": "deliverable",
            "required": False,
        }
    ]


async def test_node_cap_sets_truncated(client, session):
    owner = await mk_user(session)
    project = await _project(session, owner)
    for i in range(3):
        await _doc(session, owner, project, f"D{i}")
    await session.commit()

    await login_as(client, owner)
    body = (await client.get(f"/api/projects/{project.slug}/graph?max_nodes=2")).json()
    assert len(body["nodes"]) == 2
    assert body["truncated"] is True


async def _seed_project(session, size: int) -> tuple:
    owner = await mk_user(session)
    project = await _project(session, owner)
    docs = [
        Asset(
            slug=generate_slug(),
            owner_id=owner.id,
            project_id=project.id,
            kind="md_single",
            title=f"n{i}",
            storage_prefix=generate_slug(8),
            entry_path="doc.md",
            security_status="clean",
            version=1,
            summary=f"summary {i}",
        )
        for i in range(size)
    ]
    outside = await mk_asset(session, owner, title="Outside")
    session.add_all(docs)
    await session.flush()
    session.add_all(_rel(docs[i], docs[i + 1]) for i in range(0, size - 1, 2))
    session.add_all(_rel(docs[i], outside, "references") for i in range(0, size, 10))
    session.add_all(
        AssetExternalRef(
            asset_id=docs[i].id,
            system="openproject",
            entity="work_package",
            external_id=str(i),
            role="context",
            origin="manual",
        )
        for i in range(0, size, 5)
    )
    await session.commit()
    return owner, project


async def _count_statements(client, session, slug: str) -> tuple[int, dict]:
    statements: list[str] = []

    def _count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _count)
    try:
        r = await client.get(f"/api/projects/{slug}/graph?include=tasks")
    finally:
        event.remove(engine, "before_cursor_execute", _count)
    assert r.status_code == 200, r.text
    return len(statements), r.json()


async def test_statement_count_does_not_grow_with_the_project(client, session):
    small_owner, small = await _seed_project(session, 50)
    big_owner, big = await _seed_project(session, 500)

    await login_as(client, small_owner)
    small_count, small_body = await _count_statements(client, session, small.slug)
    await login_as(client, big_owner)
    big_count, big_body = await _count_statements(client, session, big.slug)

    assert len(small_body["nodes"]) == 51
    assert len(big_body["nodes"]) == 501
    assert len(big_body["tasks"]) == 100
    assert big_count == small_count, (small_count, big_count)
