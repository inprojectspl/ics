"""Rekey (ADR-0018): links of a Project Standard node move to the OpenProject
work package created for it, only on the project's own assets."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import AssetExternalRef, AssetProjectShare, AuditLog, Project, ProjectMember
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_user

NODE = {"system": "project_standard", "external_scope": "ics", "external_id": "n-8f2c"}
WP = {"system": "openproject", "entity": "work_package", "external_id": "4711"}


def _node_ref(asset, role="context", **kw) -> AssetExternalRef:
    return AssetExternalRef(
        asset_id=asset.id,
        system="project_standard",
        entity="node",
        external_scope="ics",
        external_id="n-8f2c",
        role=role,
        origin="agent",
        **kw,
    )


async def _seed(session):
    owner = await mk_user(session)
    editor = await mk_user(session)
    project = Project(slug=generate_slug(), name="Rekey", created_by=owner.id)
    other = Project(slug=generate_slug(), name="Other", created_by=owner.id)
    session.add_all([project, other])
    await session.flush()
    now = datetime.now(UTC)
    session.add_all(
        [
            ProjectMember(project_id=project.id, user_id=owner.id, role="owner", accepted_at=now),
            ProjectMember(project_id=project.id, user_id=editor.id, role="editor", accepted_at=now),
        ]
    )
    home = await mk_asset(session, owner)
    home.project_id = project.id
    assigned = await mk_asset(session, owner)
    assigned.project_id = other.id
    foreign = await mk_asset(session, owner)
    foreign.project_id = other.id
    await session.flush()
    session.add(AssetProjectShare(asset_id=assigned.id, project_id=project.id, role="editor"))
    session.add_all(
        [
            _node_ref(home),
            _node_ref(home, role="deliverable", asset_path="report.md"),
            _node_ref(assigned),
            _node_ref(foreign),
        ]
    )
    await session.commit()
    return owner, editor, project, home, assigned, foreign


async def _keys(session, asset) -> set[tuple[str, str, str]]:
    rows = await session.execute(
        select(AssetExternalRef.system, AssetExternalRef.external_id, AssetExternalRef.role).where(
            AssetExternalRef.asset_id == asset.id
        )
    )
    return {tuple(r) for r in rows.all()}


async def _rekey(client, project):
    return await client.post(
        "/api/external-refs/rekey", json={"project_slug": project.slug, "from": NODE, "to": WP}
    )


@pytest.mark.asyncio
async def test_moves_project_refs_and_skips_foreign(client, session):
    owner, _editor, project, home, assigned, foreign = await _seed(session)
    await login_as(client, owner)

    r = await _rekey(client, project)
    assert r.status_code == 200
    assert r.json() == {"moved": 3, "merged": 0}

    session.expunge_all()
    assert await _keys(session, home) == {
        ("openproject", "4711", "context"),
        ("openproject", "4711", "deliverable"),
    }
    assert await _keys(session, assigned) == {("openproject", "4711", "context")}
    assert await _keys(session, foreign) == {("project_standard", "n-8f2c", "context")}
    moved = await session.scalar(
        select(AssetExternalRef).where(
            AssetExternalRef.asset_id == assigned.id, AssetExternalRef.system == "openproject"
        )
    )
    assert moved is not None
    assert (moved.entity, moved.external_scope) == ("work_package", None)

    payload = await session.scalar(
        select(AuditLog.payload).where(
            AuditLog.action == "external_refs_rekeyed", AuditLog.target == f"project:{project.id}"
        )
    )
    assert payload["moved"] == 3


@pytest.mark.asyncio
async def test_existing_target_ref_is_not_duplicated(client, session):
    owner, _editor, project, home, _assigned, _foreign = await _seed(session)
    session.add(AssetExternalRef(asset_id=home.id, role="context", origin="manual", **WP))
    await session.commit()
    await login_as(client, owner)

    r = await _rekey(client, project)
    assert r.json() == {"moved": 2, "merged": 1}
    session.expunge_all()
    rows = (
        await session.scalars(select(AssetExternalRef).where(AssetExternalRef.asset_id == home.id))
    ).all()
    assert sorted((r.system, r.role) for r in rows) == [
        ("openproject", "context"),
        ("openproject", "deliverable"),
    ]


@pytest.mark.asyncio
async def test_non_owner_is_refused(client, session):
    _owner, editor, project, home, _assigned, _foreign = await _seed(session)
    await login_as(client, editor)
    r = await _rekey(client, project)
    assert r.status_code == 403
    assert r.json()["code"] == "project_role_required"

    stranger = await mk_user(session)
    await session.commit()
    await login_as(client, stranger)
    r = await _rekey(client, project)
    assert r.status_code == 404
    session.expunge_all()
    assert ("project_standard", "n-8f2c", "context") in await _keys(session, home)


@pytest.mark.asyncio
async def test_malformed_keys_are_rejected(client, session):
    owner, _editor, project, *_rest = await _seed(session)
    await login_as(client, owner)
    r = await client.post(
        "/api/external-refs/rekey",
        json={
            "project_slug": project.slug,
            "from": NODE,
            "to": {**WP, "external_id": "WP-1"},
        },
    )
    assert r.status_code == 400
    assert r.json()["code"] == "external_ref_invalid"
