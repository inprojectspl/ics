"""Project hygiene lists (GET /api/projects/{slug}/hygiene): owners and editors
only, counters in one statement, and edges to unreadable documents counted
without exposing them."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import event

from app.models import (
    AssetExternalRef,
    AssetProjectShare,
    AssetRelation,
    AssetShare,
    Project,
    ProjectMember,
)
from app.services import project_hygiene
from app.slug import generate_slug
from tests.conftest import login_as, mk_admin, mk_asset, mk_doc_type, mk_user


def _rel(source, target, relation_type="references", target_version=None) -> AssetRelation:
    return AssetRelation(
        source_asset_id=source.id,
        target_asset_id=target.id,
        relation_type=relation_type,
        target_version=target_version,
        origin="manual",
    )


async def _project(session, owner, *members) -> Project:
    project = Project(slug=generate_slug(), name="Hygiene", created_by=owner.id)
    session.add(project)
    await session.flush()
    now = datetime.now(UTC)
    rows = [(owner, "owner"), *members]
    session.add_all(
        ProjectMember(project_id=project.id, user_id=u.id, role=role, accepted_at=now)
        for u, role in rows
    )
    await session.flush()
    return project


async def _doc(session, owner, project, title, **fields):
    asset = await mk_asset(session, owner, title=title)
    asset.project_id = project.id
    for key, value in fields.items():
        setattr(asset, key, value)
    return asset


async def _seed(session):
    owner = await mk_user(session)
    editor = await mk_user(session)
    viewer = await mk_user(session)
    outsider = await mk_user(session)
    project = await _project(session, owner, (editor, "editor"), (viewer, "viewer"))
    doc_type = await mk_doc_type(session)
    past = datetime.now(UTC) - timedelta(days=1)

    tidy = await _doc(
        session, owner, project, "Tidy", summary="ok", summary_version=1, doc_type=doc_type.key
    )
    bare = await _doc(session, owner, project, "Bare")
    stale = await _doc(
        session, owner, project, "Stale", summary="old", summary_version=1, version=3
    )
    overdue = await _doc(
        session, owner, project, "Overdue", summary="x", summary_version=1, review_due_at=past
    )
    basis = await _doc(session, owner, project, "Derived", summary="x", summary_version=1)
    source = await _doc(session, owner, project, "Source", version=4)
    old = await _doc(session, owner, project, "Old spec", summary="x", summary_version=1)
    new = await _doc(session, owner, project, "New spec", summary="x", summary_version=1)
    assigned = await mk_asset(session, outsider, title="Assigned")
    session.add(AssetProjectShare(asset_id=assigned.id, project_id=project.id, role="viewer"))
    secret = await mk_asset(session, outsider, title="Top secret plan")
    session.add_all(
        [
            _rel(basis, source, "derived_from", target_version=2),
            _rel(tidy, source, "derived_from", target_version=4),
            _rel(new, old, "supersedes"),
            _rel(tidy, secret),
            _rel(bare, secret, "depends_on"),
        ]
    )
    session.add(
        AssetExternalRef(
            asset_id=old.id,
            system="openproject",
            entity="work_package",
            external_id="7",
            role="context",
            origin="manual",
        )
    )
    await session.commit()
    return {
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "outsider": outsider,
        "project": project,
        "secret": secret,
        "docs": {
            "tidy": tidy,
            "bare": bare,
            "stale": stale,
            "overdue": overdue,
            "basis": basis,
            "source": source,
            "old": old,
            "new": new,
            "assigned": assigned,
        },
    }


async def test_viewer_and_stranger_get_404(client, session):
    s = await _seed(session)
    for user in (s["viewer"], s["outsider"]):
        await login_as(client, user)
        r = await client.get(f"/api/projects/{s['project'].slug}/hygiene")
        assert r.status_code == 404
        assert r.json()["code"] == "project_not_found"
    for user in (s["owner"], s["editor"], await mk_admin(session)):
        await session.commit()
        await login_as(client, user)
        r = await client.get(f"/api/projects/{s['project'].slug}/hygiene")
        assert r.status_code == 200, r.text


async def test_lists_and_counters(client, session):
    s = await _seed(session)
    d = s["docs"]
    await login_as(client, s["editor"])

    async def slugs(name: str) -> tuple[set[str], dict]:
        r = await client.get(f"/api/projects/{s['project'].slug}/hygiene?list={name}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == len(body["items"])
        return {i["slug"] for i in body["items"]}, body["counters"]

    no_summary, counters = await slugs("no_summary")
    assert no_summary == {d["bare"].slug, d["source"].slug, d["assigned"].slug}
    assert (await slugs("summary_stale"))[0] == {d["stale"].slug}
    assert d["tidy"].slug not in (await slugs("no_doc_type"))[0]
    assert (await slugs("review_overdue"))[0] == {d["overdue"].slug}
    assert (await slugs("basis_changed"))[0] == {d["basis"].slug}
    assert (await slugs("superseded_linked"))[0] == {d["old"].slug}
    assert counters["no_doc_type"] == 8
    assert counters["hidden_edges"] == 2

    r = await client.get(f"/api/projects/{s['project'].slug}/hygiene?list=bogus")
    assert r.status_code == 422


async def test_hidden_edge_is_counted_without_its_title(client, session):
    s = await _seed(session)
    await login_as(client, s["owner"])
    r = await client.get(f"/api/projects/{s['project'].slug}/hygiene?list=hidden_edges")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["counters"]["hidden_edges"] == 2
    items = {i["slug"]: i["hidden_edges"] for i in body["items"]}
    assert items == {s["docs"]["tidy"].slug: 1, s["docs"]["bare"].slug: 1}
    assert "Top secret plan" not in r.text

    # Once the outsider shares it, the edge is no longer hidden.
    session.add(AssetShare(asset_id=s["secret"].id, user_id=s["owner"].id, role="viewer"))
    await session.commit()
    r = await client.get(f"/api/projects/{s['project'].slug}/hygiene?list=hidden_edges")
    assert r.json()["counters"]["hidden_edges"] == 0


async def test_counters_are_one_statement(session):
    s = await _seed(session)
    statements: list[str] = []

    def _count(_conn, _cursor, statement, *_args):
        statements.append(statement)

    engine = session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", _count)
    try:
        counters = await project_hygiene.counters(session, s["editor"], s["project"])
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert len(statements) == 1, statements
    assert "FILTER (WHERE" in statements[0]
    assert set(counters) == set(project_hygiene.HYGIENE_LISTS)


async def test_pagination(client, session):
    owner = await mk_user(session)
    project = await _project(session, owner)
    for i in range(project_hygiene.PAGE_SIZE + 3):
        await _doc(session, owner, project, f"D{i:02d}")
    await session.commit()

    await login_as(client, owner)
    base = f"/api/projects/{project.slug}/hygiene?list=no_summary"
    first = (await client.get(base)).json()
    second = (await client.get(base + "&page=2")).json()
    assert first["total"] == project_hygiene.PAGE_SIZE + 3
    assert len(first["items"]) == project_hygiene.PAGE_SIZE
    assert len(second["items"]) == 3


async def test_hidden_changed_basis_is_not_listed(session):
    """A `derived_from` target the viewer cannot read never marks the basis
    as changed: the list would confirm that a newer hidden version exists."""
    s = await _seed(session)
    derived = await _doc(session, s["owner"], s["project"], "Derived from secret")
    s["secret"].version = 5
    session.add(_rel(derived, s["secret"], "derived_from", target_version=1))
    await session.commit()

    counters = await project_hygiene.counters(session, s["editor"], s["project"])
    items = await project_hygiene.page(session, s["editor"], s["project"], "basis_changed", 1)
    assert counters["basis_changed"] == 1
    assert {i["slug"] for i in items} == {s["docs"]["basis"].slug}

    # Once the editor can read the target, the changed basis shows up.
    session.add(AssetShare(asset_id=s["secret"].id, user_id=s["editor"].id, role="viewer"))
    await session.commit()
    counters = await project_hygiene.counters(session, s["editor"], s["project"])
    assert counters["basis_changed"] == 2
