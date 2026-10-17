"""Document to task links (ADR-0018): graph access gates reading, editor gates
writing, keys are validated, and the label is kept as plain text."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import AssetShare, AuditLog, Project, ProjectMember
from app.services import external_refs
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_user

WP = {"system": "openproject", "entity": "work_package", "external_id": "4711"}


async def _seed(session):
    owner = await mk_user(session)
    member = await mk_user(session)
    share_viewer = await mk_user(session)
    project = Project(slug=generate_slug(), name="Links", created_by=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(
            project_id=project.id, user_id=member.id, role="viewer", accepted_at=datetime.now(UTC)
        )
    )
    asset = await mk_asset(session, owner)
    asset.project_id = project.id
    session.add(AssetShare(asset_id=asset.id, user_id=share_viewer.id, role="viewer"))
    await session.commit()
    return owner, member, share_viewer, asset


@pytest.mark.asyncio
async def test_list_needs_graph_access(client, session):
    owner, member, share_viewer, asset = await _seed(session)
    await login_as(client, owner)
    r = await client.post(
        f"/api/assets/{asset.id}/external-refs",
        json={**WP, "role": "context", "required": True, "label": "<b>Story</b>\n x"},
    )
    assert r.status_code == 201
    created = r.json()
    assert created["origin"] == "manual"
    assert created["required"] is True
    assert created["pinned_version"] == 1
    assert created["label"] == "<b>Story</b> x"

    await login_as(client, share_viewer)
    r = await client.get(f"/api/assets/{asset.id}/external-refs")
    assert r.status_code == 404
    assert r.json()["code"] == "asset_not_found"

    await login_as(client, member)
    r = await client.get(f"/api/assets/{asset.id}/external-refs")
    assert r.status_code == 200
    assert [x["external_id"] for x in r.json()] == ["4711"]
    # A viewer cannot remove it: same answer as a missing link.
    r = await client.delete(f"/api/external-refs/{created['id']}")
    assert r.status_code == 404
    assert r.json()["code"] == "external_ref_not_found"

    await login_as(client, owner)
    assert (await client.delete(f"/api/external-refs/{created['id']}")).status_code == 200
    actions = (
        await session.scalars(
            select(AuditLog.action)
            .where(AuditLog.target == f"asset:{asset.id}")
            .order_by(AuditLog.id)
        )
    ).all()
    assert actions == ["external_ref_added", "external_ref_removed"]


@pytest.mark.asyncio
async def test_duplicate_is_409(client, session):
    owner, *_rest, asset = await _seed(session)
    await login_as(client, owner)
    url = f"/api/assets/{asset.id}/external-refs"
    assert (await client.post(url, json={**WP, "role": "context"})).status_code == 201
    r = await client.post(url, json={**WP, "role": "context"})
    assert r.status_code == 409
    assert r.json()["code"] == "external_ref_exists"
    # Another role is another link.
    assert (await client.post(url, json={**WP, "role": "deliverable"})).status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {**WP, "external_id": "WP-4711"},
        {"system": "project_standard", "entity": "node", "external_id": "n-8f2c"},
        {
            "system": "project_standard",
            "entity": "node",
            "external_id": "node 8",
            "external_scope": "ics",
        },
        {**WP, "system": "jira"},
        {**WP, "role": "must_read"},
        {**WP, "url": "javascript:alert(1)"},
        {**WP, "pinned_version": 7},
    ],
)
async def test_format_validation(client, session, body):
    owner, *_rest, asset = await _seed(session)
    await login_as(client, owner)
    r = await client.post(f"/api/assets/{asset.id}/external-refs", json=body)
    assert r.status_code == 400
    assert r.json()["code"] == "external_ref_invalid"


@pytest.mark.asyncio
async def test_ps_node_with_scope_and_limit(session, monkeypatch):
    owner, *_rest, asset = await _seed(session)
    ref = await external_refs.add_ref(
        session,
        actor=owner,
        asset_id=asset.id,
        system="project_standard",
        entity="node",
        external_id="n-8f2c",
        external_scope="ics",
        role="deliverable",
        transport="bearer",
    )
    assert ref.origin == "agent"

    monkeypatch.setattr(external_refs, "MAX_REFS_PER_ASSET", 2)
    await external_refs.add_ref(session, actor=owner, asset_id=asset.id, role="context", **WP)
    with pytest.raises(external_refs.LimitExceededError) as exc:
        await external_refs.add_ref(session, actor=owner, asset_id=asset.id, role="reference", **WP)
    assert exc.value.code == "external_ref_limit"


@pytest.mark.asyncio
async def test_viewer_cannot_add_and_stranger_sees_404(client, session):
    _owner, member, _v, asset = await _seed(session)
    stranger = await mk_user(session)
    await session.commit()
    for user in (member, stranger):
        await login_as(client, user)
        r = await client.post(
            f"/api/assets/{asset.id}/external-refs", json={**WP, "role": "context"}
        )
        assert r.status_code == 404
        assert r.json()["code"] == "asset_not_found"


@pytest.mark.asyncio
async def test_single_link_in_compact_shape_follows_list_access(client, session):
    owner, member, share_viewer, asset = await _seed(session)
    await login_as(client, owner)
    r = await client.post(
        f"/api/assets/{asset.id}/external-refs",
        json={**WP, "role": "context", "required": True, "label": "Story", "note": "The contract"},
    )
    ref_id = r.json()["id"]
    r = await client.post(f"/api/assets/{asset.id}/external-refs", json={**WP, "role": "reference"})
    plain_id = r.json()["id"]

    await login_as(client, member)
    r = await client.get(f"/api/external-refs/{ref_id}")
    assert r.status_code == 200
    assert r.json() == {
        "id": ref_id,
        "asset": {"slug": asset.slug, "title": asset.title},
        "system": "openproject",
        "external_id": "4711",
        "role": "context",
        "required": True,
        "label": "Story",
        "note": "The contract",
    }
    r = await client.get(f"/api/external-refs/{plain_id}")
    assert set(r.json()) == {"id", "asset", "system", "external_id", "role"}

    # No graph access: the same 404 as a missing link.
    missing = await client.get(f"/api/external-refs/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "external_ref_not_found"
    await login_as(client, share_viewer)
    r = await client.get(f"/api/external-refs/{ref_id}")
    assert (r.status_code, r.json()) == (404, missing.json())
