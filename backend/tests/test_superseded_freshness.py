"""Graph signals in asset projections (ADR-0015 section 4, ADR-0016 section 7):
`superseded` with a visible successor, `basis_changed` after a new version of
a `derived_from` target, both computed in bulk for listings."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event

from app.models import AssetRelation, Project, ProjectMember
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_md_single, mk_user


async def _add(client, source, target, relation_type):
    r = await client.post(
        f"/api/assets/{source.id}/relations",
        json={"relation_type": relation_type, "target_id": str(target.id)},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _project_with(session, owner, *assets):
    project = Project(slug=generate_slug(), name="Signals", created_by=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(
            project_id=project.id, user_id=owner.id, role="owner", accepted_at=datetime.now(UTC)
        )
    )
    for a in assets:
        a.project_id = project.id
    await session.commit()
    return project


def _row(items, asset):
    return next(i for i in items if i["id"] == str(asset.id))


async def _views(client, asset, project):
    """The asset as /meta, /index, the home list and the project list show it."""
    meta = (await client.get(f"/api/assets/by-slug/{asset.slug}/meta")).json()
    index = _row((await client.get("/api/assets/index")).json()["items"], asset)
    home = _row((await client.get("/api/assets")).json()["items"], asset)
    proj = _row((await client.get(f"/api/projects/{project.slug}")).json()["assets"], asset)
    return [meta, index, home, proj]


@pytest.mark.asyncio
async def test_superseded_everywhere_and_removal_restores_freshness(client, session):
    owner = await mk_user(session)
    old = await mk_asset(session, owner, title="Spec v2")
    new = await mk_asset(session, owner, title="Spec v3")
    old.review_due_at = datetime.now(UTC) - timedelta(days=1)
    project = await _project_with(session, owner, old, new)
    await login_as(client, owner)

    for view in await _views(client, old, project):
        assert view["freshness"] == "review_overdue"
        assert view["superseded_by"] is None

    edge_id = await _add(client, new, old, "supersedes")
    for view in await _views(client, old, project):
        assert view["freshness"] == "superseded"
        assert view["superseded_by"] == {"id": str(new.id), "slug": new.slug, "title": "Spec v3"}
    for view in await _views(client, new, project):
        assert view["freshness"] == "current"

    assert (await client.delete(f"/api/relations/{edge_id}")).status_code in (200, 204)
    for view in await _views(client, old, project):
        assert view["freshness"] == "review_overdue"
        assert view["superseded_by"] is None


@pytest.mark.asyncio
async def test_invisible_successor_does_not_supersede(client, session):
    reader = await mk_user(session)
    stranger = await mk_user(session)
    old = await mk_asset(session, reader, title="Visible")
    hidden = await mk_asset(session, stranger, title="Hidden successor")
    session.add(
        AssetRelation(
            source_asset_id=hidden.id,
            target_asset_id=old.id,
            relation_type="supersedes",
            target_version=1,
            origin="manual",
            created_by=stranger.id,
        )
    )
    await session.commit()
    await login_as(client, reader)

    r = await client.get(f"/api/assets/by-slug/{old.slug}/meta")
    assert r.json()["freshness"] == "current"
    assert r.json()["superseded_by"] is None
    assert hidden.slug not in r.text
    row = _row((await client.get("/api/assets")).json()["items"], old)
    assert row["freshness"] == "current"
    assert row["superseded_by"] is None


@pytest.mark.asyncio
async def test_superseded_ranks_lower_in_search(client, session):
    owner = await mk_user(session)
    old = await mk_asset(session, owner, title="Quarterly roadmap")
    new = await mk_asset(session, owner, title="Quarterly roadmap")
    old.search_content = new.search_content = "roadmap milestones"
    await session.commit()
    await login_as(client, owner)

    async def scores():
        r = await client.get("/api/assets/search-mcp", params={"q": "roadmap"})
        return {i["id"]: i["score"] for i in r.json()["items"]}

    before = await scores()
    assert before[str(old.id)] == pytest.approx(before[str(new.id)])
    await _add(client, new, old, "supersedes")
    after = await scores()
    assert after[str(old.id)] == pytest.approx(after[str(new.id)] / 2)
    r = await client.get("/api/assets/search-mcp", params={"q": "roadmap"})
    ids = [i["id"] for i in r.json()["items"]]
    assert ids.index(str(new.id)) < ids.index(str(old.id))


@pytest.mark.asyncio
async def test_basis_changed_after_new_target_version_and_refresh_clears(
    client, session, fs_storage
):
    owner, basis = await mk_md_single(client, session, content="# Goals\n")
    design = await mk_asset(session, owner, title="Design")
    await session.commit()
    edge_id = await _add(client, design, basis, "derived_from")

    meta = (await client.get(f"/api/assets/by-slug/{design.slug}/meta")).json()
    assert "basis_changed" not in meta["flags"]

    r = await client.put(f"/api/assets/{basis.id}/content", json={"content": "# Goals v2\n"})
    assert r.status_code == 201

    meta = (await client.get(f"/api/assets/by-slug/{design.slug}/meta")).json()
    assert "basis_changed" in meta["flags"]
    row = _row((await client.get("/api/assets")).json()["items"], design)
    assert "basis_changed" in row["flags"]
    rels = (await client.get(f"/api/assets/by-slug/{design.slug}/relations")).json()
    (edge,) = rels["outgoing"]["derived_from"]
    assert edge["target_version"] == 1
    assert edge["target_version_now"] == 2
    assert edge["target_changed"] is True

    r = await client.patch(f"/api/relations/{edge_id}", json={"refresh_target_version": True})
    assert r.status_code == 200
    meta = (await client.get(f"/api/assets/by-slug/{design.slug}/meta")).json()
    assert "basis_changed" not in meta["flags"]
    rels = (await client.get(f"/api/assets/by-slug/{design.slug}/relations")).json()
    assert rels["outgoing"]["derived_from"][0]["target_changed"] is False


@contextmanager
def _count_statements(session) -> Iterator[list[str]]:
    statements: list[str] = []
    engine = session.bind.sync_engine

    def _on_execute(_conn, _cursor, statement, *_args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _on_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _on_execute)


async def _listing_statements(client, session, n: int) -> tuple[int, int, int]:
    owner = await mk_user(session)
    assets = [await mk_asset(session, owner, title=f"Doc {i}") for i in range(n)]
    # Every other asset is superseded, every third derived from a newer basis.
    for i, a in enumerate(assets[1:], start=1):
        prev = assets[i - 1]
        relation = "supersedes" if i % 2 else "derived_from"
        session.add(
            AssetRelation(
                source_asset_id=a.id if relation == "supersedes" else prev.id,
                target_asset_id=prev.id if relation == "supersedes" else a.id,
                relation_type=relation,
                target_version=0,
                origin="manual",
                created_by=owner.id,
            )
        )
    project = await _project_with(session, owner, *assets)
    await login_as(client, owner)

    counts = []
    for url, key in (
        ("/api/assets?page_size=100", "items"),
        ("/api/assets/index?limit=100", "items"),
        (f"/api/projects/{project.slug}", "assets"),
    ):
        with _count_statements(session) as stmts:
            r = await client.get(url)
        assert r.status_code == 200
        rows = r.json()[key]
        assert len(rows) == n
        assert any(row["freshness"] == "superseded" for row in rows)
        assert any("basis_changed" in row["flags"] for row in rows)
        counts.append(len(stmts))
    return counts[0], counts[1], counts[2]


@pytest.mark.asyncio
async def test_listing_statement_count_is_constant(client, session):
    few = await _listing_statements(client, session, 5)
    await client.post("/api/auth/logout")
    many = await _listing_statements(client, session, 50)
    assert min(few) > 0
    assert few == many
