"""A PS node belongs to its project; OP work packages keep one global identity."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import AssetExternalRef, Project, ProjectMember
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_user

NODE = {"system": "project_standard", "entity": "node", "external_id": "n-8f2c"}
WP = {"system": "openproject", "entity": "work_package", "external_id": "4711"}


async def _seed(client, session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner)
    asset.version = 2
    project = Project(slug=generate_slug(), name="Scoped references", created_by=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(
            project_id=project.id, user_id=owner.id, role="owner", accepted_at=datetime.now(UTC)
        )
    )
    asset.project_id = project.id
    await session.commit()
    await login_as(client, owner)
    return asset, project


async def _add(client, asset, scope, **kwargs):
    return await client.post(
        f"/api/assets/{asset.id}/external-refs",
        json={**NODE, "external_scope": scope, "role": "context", **kwargs},
    )


@pytest.mark.asyncio
async def test_same_node_in_two_projects_has_independent_context_packs(client, session):
    asset, _ = await _seed(client, session)
    a = await _add(client, asset, "project-a", required=True, pinned_version=1, label="A")
    b = await _add(client, asset, "project-b", required=False, pinned_version=2, label="B")
    assert (a.status_code, b.status_code) == (201, 201), (a.text, b.text)
    assert a.json()["id"] != b.json()["id"]
    for scope, label, required, changed in (
        ("project-a", "A", True, True),
        ("project-b", "B", False, False),
    ):
        response = await client.get(
            "/api/context", params={"system": "project_standard", "wp": "n-8f2c", "scope": scope}
        )
        assert response.status_code == 200, response.text
        docs = response.json()["documents"]
        assert [doc["slug"] for doc in docs] == [asset.slug]
        assert docs[0]["via"] == [
            {"kind": "direct", "role": "context", "required": required, "label": label}
        ]
        assert docs[0].get("required", False) is required
        assert ("basis_changed" in docs[0].get("flags", [])) is changed


@pytest.mark.asyncio
@pytest.mark.parametrize("retry", [{}, {"required": True}, {"pinned_version": 1}])
async def test_retry_is_an_explicit_conflict_without_changing_required_or_pin(
    client, session, retry
):
    asset, _ = await _seed(client, session)
    created = await _add(client, asset, "project-a", pinned_version=2)
    assert created.status_code == 201
    response = await _add(client, asset, "project-a", **retry)
    assert response.status_code == 409
    assert response.json()["code"] == "external_ref_exists"
    refs = (await client.get(f"/api/assets/{asset.id}/external-refs")).json()
    assert len(refs) == 1
    assert refs[0]["id"] == created.json()["id"]
    assert refs[0]["required"] is False
    assert refs[0]["pinned_version"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_target", [False, True])
async def test_rekey_only_moves_or_merges_the_selected_scope(client, session, existing_target):
    asset, project = await _seed(client, session)
    for scope in ("project-a", "project-b"):
        response = await _add(client, asset, scope)
        assert response.status_code == 201, response.text
    before = (await client.get(f"/api/assets/{asset.id}/external-refs")).json()
    untouched = next(ref for ref in before if ref["external_scope"] == "project-b")
    if existing_target:
        response = await client.post(
            f"/api/assets/{asset.id}/external-refs", json={**WP, "role": "context"}
        )
        assert response.status_code == 201
    response = await client.post(
        "/api/external-refs/rekey",
        json={
            "project_slug": project.slug,
            "from": {**NODE, "external_scope": "project-a"},
            "to": WP,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"moved": int(not existing_target), "merged": int(existing_target)}
    refs = (await client.get(f"/api/assets/{asset.id}/external-refs")).json()
    assert len(refs) == 2
    assert next(ref for ref in refs if ref["system"] == "project_standard") == untouched
    assert next(ref for ref in refs if ref["system"] == "openproject")["external_scope"] is None


@pytest.mark.asyncio
async def test_openproject_scope_does_not_create_another_instance(client, session):
    asset, _ = await _seed(client, session)
    url = f"/api/assets/{asset.id}/external-refs"
    assert (await client.post(url, json={**WP, "role": "context"})).status_code == 201
    response = await client.post(url, json={**WP, "role": "context", "external_scope": "other"})
    assert response.status_code == 409
    assert response.json()["code"] == "external_ref_exists"
    refs = (
        await session.scalars(select(AssetExternalRef).where(AssetExternalRef.asset_id == asset.id))
    ).all()
    assert len(refs) == 1
