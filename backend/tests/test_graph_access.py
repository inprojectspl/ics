"""Graph access predicate (ADR-0016, section 5).

Graph access is narrower than content access: a user whose only source is a
direct viewer share reads the document but gets no relations or
neighbourhood. The SQL filter and the Python predicate must agree.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import Asset, AssetShare, Project, ProjectMember
from app.permissions import graph_accessible_assets_filter, has_graph_access
from app.slug import generate_slug
from tests.conftest import mk_admin, mk_asset, mk_user

EXPECTED = {
    "admin": True,
    "owner": True,
    "project_owner": True,
    "project_editor": True,
    "project_viewer": True,
    "share_editor": True,
    "share_viewer": False,
    "pending_member": False,
    "other_project_member": False,
    "stranger": False,
}


async def _seed(session):
    owner = await mk_user(session)
    project = Project(slug=generate_slug(), name="Graph", created_by=owner.id)
    other = Project(slug=generate_slug(), name="Other", created_by=owner.id)
    session.add_all([project, other])
    await session.flush()

    principals = {"owner": owner, "admin": await mk_admin(session)}
    for name in EXPECTED:
        if name not in principals:
            principals[name] = await mk_user(session)

    now = datetime.now(UTC)
    members = [
        ("project_owner", project, "owner", now),
        ("project_editor", project, "editor", now),
        ("project_viewer", project, "viewer", now),
        ("pending_member", project, "editor", None),
        ("other_project_member", other, "owner", now),
    ]
    session.add_all(
        ProjectMember(
            project_id=proj.id, user_id=principals[name].id, role=role, accepted_at=accepted
        )
        for name, proj, role, accepted in members
    )

    async def _asset() -> Asset:
        a = await mk_asset(session, owner)
        a.project_id = project.id
        session.add_all(
            [
                AssetShare(asset_id=a.id, user_id=principals["share_editor"].id, role="editor"),
                AssetShare(asset_id=a.id, user_id=principals["share_viewer"].id, role="viewer"),
            ]
        )
        return a

    asset = await _asset()
    deleted = await _asset()
    deleted.deleted_at = now
    await session.commit()
    return principals, asset, deleted


async def _sql_ids(session, user, ids) -> set:
    rows = await session.execute(
        select(Asset.id).where(Asset.id.in_(ids), graph_accessible_assets_filter(user))
    )
    return set(rows.scalars())


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "expected"), EXPECTED.items())
async def test_graph_access_matrix(session, name, expected):
    principals, asset, _ = await _seed(session)
    assert await has_graph_access(session, principals[name], asset) is expected


@pytest.mark.asyncio
async def test_sql_filter_matches_predicate(session):
    principals, asset, deleted = await _seed(session)
    for name, user in principals.items():
        sql = await _sql_ids(session, user, [asset.id, deleted.id])
        py = {a.id for a in (asset, deleted) if await has_graph_access(session, user, a)}
        assert sql == py, name
        assert (asset.id in sql) is EXPECTED[name], name


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["admin", "owner", "project_owner", "share_editor"])
async def test_deleted_asset_has_no_graph_access(session, name):
    principals, _, deleted = await _seed(session)
    assert await has_graph_access(session, principals[name], deleted) is False
    assert await _sql_ids(session, principals[name], [deleted.id]) == set()


@pytest.mark.asyncio
async def test_share_viewer_on_asset_without_project(session):
    """No home project: only owner, admin and editor shares give graph access."""
    owner = await mk_user(session)
    viewer = await mk_user(session)
    editor = await mk_user(session)
    asset = await mk_asset(session, owner)
    session.add_all(
        [
            AssetShare(asset_id=asset.id, user_id=viewer.id, role="viewer"),
            AssetShare(asset_id=asset.id, user_id=editor.id, role="editor"),
        ]
    )
    await session.commit()
    assert await has_graph_access(session, viewer, asset) is False
    assert await has_graph_access(session, editor, asset) is True
    assert await _sql_ids(session, viewer, [asset.id]) == set()
    assert await _sql_ids(session, editor, [asset.id]) == {asset.id}
