"""Project shares (ADR-0017): an asset assigned to a project other than its
home gives that project's members access and graph access, shows up in the
project's lists, and disappears with the project."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import (
    Asset,
    AssetProjectShare,
    AssetRelation,
    AuditLog,
    Project,
    ProjectMember,
)
from app.permissions import effective_role, graph_accessible_assets_filter, has_graph_access
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_user


async def _project(session, owner, **members) -> Project:
    """Project owned by `owner`; `members` maps role -> list of users."""
    project = Project(slug=generate_slug(), name=f"P {generate_slug(6)}", created_by=owner.id)
    session.add(project)
    await session.flush()
    now = datetime.now(UTC)
    session.add(
        ProjectMember(project_id=project.id, user_id=owner.id, role="owner", accepted_at=now)
    )
    for role, users in members.items():
        for u in users:
            session.add(
                ProjectMember(project_id=project.id, user_id=u.id, role=role, accepted_at=now)
            )
    await session.flush()
    return project


async def _seed(session):
    """Asset A (home H) assigned to project P as viewer. P has a viewer member."""
    owner = await mk_user(session)
    p_owner = await mk_user(session)
    p_viewer = await mk_user(session)
    stranger = await mk_user(session)
    home = await _project(session, owner)
    assigned = await _project(session, p_owner, viewer=[p_viewer])
    asset = await mk_asset(session, owner, title=f"shared-in {generate_slug(6)}")
    asset.project_id = home.id
    session.add(AssetProjectShare(asset_id=asset.id, project_id=assigned.id, role="viewer"))
    await session.commit()
    return owner, p_owner, p_viewer, stranger, home, assigned, asset


async def _graph_sql(session, user, asset) -> bool:
    row = await session.scalar(
        select(Asset.id).where(Asset.id == asset.id, graph_accessible_assets_filter(user))
    )
    return row is not None


@pytest.mark.asyncio
async def test_assigned_project_viewer_has_graph_access_stranger_not(session):
    _owner, p_owner, p_viewer, stranger, _home, _assigned, asset = await _seed(session)

    assert await effective_role(session, p_viewer, asset) == "viewer"
    assert await has_graph_access(session, p_viewer, asset) is True
    assert await _graph_sql(session, p_viewer, asset) is True
    assert await has_graph_access(session, p_owner, asset) is True

    assert await effective_role(session, stranger, asset) is None
    assert await has_graph_access(session, stranger, asset) is False
    assert await _graph_sql(session, stranger, asset) is False


@pytest.mark.asyncio
async def test_deleting_assigned_project_removes_its_shares(client, session):
    _owner, p_owner, p_viewer, _stranger, _home, assigned, asset = await _seed(session)
    await login_as(client, p_owner)

    r = await client.delete(f"/api/projects/{assigned.slug}")
    assert r.status_code == 200

    remaining = await session.scalar(
        select(AssetProjectShare.asset_id).where(AssetProjectShare.project_id == assigned.id)
    )
    assert remaining is None
    assert await effective_role(session, p_viewer, asset) is None


@pytest.mark.asyncio
async def test_project_lists_include_assigned_asset_marked(client, session):
    _owner, _p_owner, p_viewer, _stranger, home, assigned, asset = await _seed(session)
    await login_as(client, p_viewer)

    r = await client.get(f"/api/projects/{assigned.slug}")
    assert r.status_code == 200
    rows = {row["slug"]: row for row in r.json()["assets"]}
    assert rows[asset.slug]["shared_in"] is True
    assert rows[asset.slug]["project_id"] == str(home.id)
    assert rows[asset.slug]["my_role"] == "viewer"
    assert r.json()["asset_count"] == 1

    r = await client.get(f"/api/assets/index?project_id={assigned.id}")
    assert r.status_code == 200
    items = {i["slug"]: i for i in r.json()["items"]}
    assert set(items) == {asset.slug}
    assert items[asset.slug]["shared_in"] is True
    assert items[asset.slug]["access_role"] == "viewer"

    r = await client.get("/api/assets")
    assert asset.slug in {i["slug"] for i in r.json()["items"]}


@pytest.mark.asyncio
async def test_home_project_list_does_not_mark_its_own_assets(client, session):
    owner, *_rest, home, _assigned, asset = await _seed(session)
    await login_as(client, owner)
    r = await client.get(f"/api/projects/{home.slug}")
    rows = {row["slug"]: row for row in r.json()["assets"]}
    assert rows[asset.slug]["shared_in"] is False


@pytest.mark.asyncio
async def test_put_and_delete_project_share(client, session):
    owner = await mk_user(session)
    home = await _project(session, owner)
    target = await _project(session, await mk_user(session), editor=[owner])
    asset = await mk_asset(session, owner)
    asset.project_id = home.id
    await session.commit()
    await login_as(client, owner)

    r = await client.put(
        f"/api/assets/{asset.id}/project-shares",
        json={"project_id": str(target.id), "role": "editor"},
    )
    assert r.status_code == 200
    assert [(s["project_slug"], s["role"]) for s in r.json()] == [(target.slug, "editor")]

    r = await client.put(
        f"/api/assets/{asset.id}/project-shares",
        json={"project_id": str(target.id), "role": "viewer"},
    )
    assert [s["role"] for s in r.json()] == ["viewer"]

    r = await client.get(f"/api/assets/{asset.id}/project-shares")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = await client.delete(f"/api/assets/{asset.id}/project-shares/{target.id}")
    assert r.status_code == 200
    assert r.json() == []

    actions = (
        await session.scalars(
            select(AuditLog.action)
            .where(AuditLog.target == f"asset:{asset.id}")
            .order_by(AuditLog.id)
        )
    ).all()
    assert actions == [
        "asset_project_share_added",
        "asset_project_share_added",
        "asset_project_share_removed",
    ]


@pytest.mark.asyncio
async def test_put_project_share_refusals(client, session):
    owner = await mk_user(session)
    asset_viewer = await mk_user(session)
    stranger = await mk_user(session)
    home = await _project(session, owner, viewer=[asset_viewer])
    barely_member = await _project(session, await mk_user(session), viewer=[owner])
    asset = await mk_asset(session, owner)
    asset.project_id = home.id
    await session.commit()
    url = f"/api/assets/{asset.id}/project-shares"

    await login_as(client, owner)
    r = await client.put(url, json={"project_id": str(home.id), "role": "viewer"})
    assert r.status_code == 400
    assert r.json()["code"] == "project_share_home"
    r = await client.put(url, json={"project_id": str(barely_member.id), "role": "viewer"})
    assert r.status_code == 403
    assert r.json()["code"] == "project_role_required"
    r = await client.put(url, json={"project_id": str(barely_member.id), "role": "owner"})
    assert r.status_code == 422

    await login_as(client, asset_viewer)
    r = await client.get(url)
    assert r.status_code == 403
    assert r.json()["code"] == "share_forbidden"

    await login_as(client, stranger)
    r = await client.put(url, json={"project_id": str(barely_member.id), "role": "viewer"})
    assert r.status_code == 404
    assert r.json()["code"] == "asset_not_found"


@pytest.mark.asyncio
async def test_moving_asset_home_into_assigned_project_drops_the_share(client, session):
    owner, _p_owner, _p_viewer, _stranger, _home, assigned, asset = await _seed(session)
    session.add(
        ProjectMember(
            project_id=assigned.id, user_id=owner.id, role="editor", accepted_at=datetime.now(UTC)
        )
    )
    await session.commit()
    await login_as(client, owner)

    r = await client.patch(
        f"/api/assets/by-slug/{asset.slug}/project", json={"project_id": str(assigned.id)}
    )
    assert r.status_code == 200
    assert await session.get(AssetProjectShare, (asset.id, assigned.id)) is None


async def _shared_with_project_member(client, session):
    """Owner shares asset A (home H) with project P through the API; A has an
    edge to a document D of P. Returns the P member's view of it."""
    owner = await mk_user(session)
    member = await mk_user(session)
    home = await _project(session, owner)
    assigned = await _project(session, await mk_user(session), editor=[owner], viewer=[member])
    asset = await mk_asset(session, owner, title=f"shared {generate_slug(6)}")
    asset.project_id = home.id
    doc = await mk_asset(session, owner, title="In P")
    doc.project_id = assigned.id
    session.add(
        AssetRelation(
            source_asset_id=doc.id,
            target_asset_id=asset.id,
            relation_type="derived_from",
            origin="manual",
        )
    )
    await session.commit()
    await login_as(client, owner)
    r = await client.put(
        f"/api/assets/{asset.id}/project-shares",
        json={"project_id": str(assigned.id), "role": "viewer"},
    )
    assert r.status_code == 200, r.text
    return owner, member, assigned, asset


async def _member_sees(client, member, project, asset) -> tuple[bool, bool, int]:
    """(on the project list, node in the project graph, status of the asset's relations)."""
    await login_as(client, member)
    listed = await client.get(f"/api/projects/{project.slug}")
    graph = await client.get(f"/api/projects/{project.slug}/graph")
    relations = await client.get(f"/api/assets/by-slug/{asset.slug}/relations")
    return (
        asset.slug in {row["slug"] for row in listed.json()["assets"]},
        asset.slug in {n["slug"] for n in graph.json()["nodes"]},
        relations.status_code,
    )


@pytest.mark.asyncio
async def test_project_member_sees_shared_asset_on_list_and_in_graph(client, session):
    _owner, member, assigned, asset = await _shared_with_project_member(client, session)

    assert await _member_sees(client, member, assigned, asset) == (True, True, 200)


@pytest.mark.asyncio
async def test_removing_the_share_revokes_access_and_keeps_the_edge(client, session):
    owner, member, assigned, asset = await _shared_with_project_member(client, session)
    r = await client.delete(f"/api/assets/{asset.id}/project-shares/{assigned.id}")
    assert r.status_code == 200

    listed, in_graph, relations = await _member_sees(client, member, assigned, asset)
    assert (listed, in_graph, relations) == (False, False, 404)
    assert await effective_role(session, member, asset) is None
    edge = await session.scalar(
        select(AssetRelation).where(AssetRelation.target_asset_id == asset.id)
    )
    assert edge is not None
    await login_as(client, owner)
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/relations")
    assert r.status_code == 200
    assert r.json()["incoming"]["basis_for"][0]["other"]["title"] == "In P"
