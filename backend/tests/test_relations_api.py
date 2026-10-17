"""Relations API (ADR-0016): graph access gates the list, hidden ends never
appear, and a hidden target is indistinguishable from a missing one."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.models import AssetShare, Project, ProjectMember
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_user


async def _seed(session):
    """A and B in project P (member M is a viewer there), C private to
    another user. V only has a direct viewer share on A."""
    owner = await mk_user(session)
    member = await mk_user(session)
    share_viewer = await mk_user(session)
    project = Project(slug=generate_slug(), name="Rel", created_by=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(
            project_id=project.id, user_id=member.id, role="viewer", accepted_at=datetime.now(UTC)
        )
    )
    a = await mk_asset(session, owner, title="A")
    b = await mk_asset(session, owner, title="B")
    a.project_id = b.project_id = project.id
    c = await mk_asset(session, owner, title="C")
    session.add(AssetShare(asset_id=a.id, user_id=share_viewer.id, role="viewer"))
    await session.commit()
    return owner, member, share_viewer, a, b, c


async def _add(client, source, target, relation_type="depends_on", **extra):
    return await client.post(
        f"/api/assets/{source.id}/relations",
        json={"relation_type": relation_type, "target_id": str(target.id), **extra},
    )


@pytest.mark.asyncio
async def test_edge_to_invisible_document_is_not_listed(client, session):
    owner, member, _v, a, b, c = await _seed(session)
    await login_as(client, owner)
    assert (await _add(client, a, b)).status_code == 201
    assert (await _add(client, a, c)).status_code == 201

    r = await client.get(f"/api/assets/by-slug/{a.slug}/relations")
    assert {e["other"]["slug"] for e in r.json()["outgoing"]["depends_on"]} == {b.slug, c.slug}

    await login_as(client, member)
    r = await client.get(f"/api/assets/by-slug/{a.slug}/relations")
    assert r.status_code == 200
    edges = r.json()["outgoing"]["depends_on"]
    assert [e["other"]["slug"] for e in edges] == [b.slug]
    assert "hidden" not in r.text


@pytest.mark.asyncio
async def test_share_only_viewer_gets_404_project_viewer_gets_list(client, session):
    owner, member, share_viewer, a, b, _c = await _seed(session)
    await login_as(client, owner)
    await _add(client, a, b)

    await login_as(client, share_viewer)
    r = await client.get(f"/api/assets/by-slug/{a.slug}/relations")
    missing = await client.get(f"/api/assets/by-slug/{generate_slug()}/relations")
    assert r.status_code == 404
    assert r.json() == missing.json()
    assert r.json()["code"] == "asset_not_found"

    await login_as(client, member)
    r = await client.get(f"/api/assets/by-slug/{b.slug}/relations")
    assert r.status_code == 200
    (edge,) = r.json()["incoming"]["required_by"]
    assert edge["label"] == "required_by"
    assert edge["other"]["slug"] == a.slug


@pytest.mark.asyncio
async def test_post_with_invisible_target_matches_nonexistent_target(client, session):
    editor = await mk_user(session)
    other = await mk_user(session)
    source = await mk_asset(session, editor)
    hidden = await mk_asset(session, other)
    await session.commit()
    await login_as(client, editor)

    r_hidden = await _add(client, source, hidden)
    r_missing = await client.post(
        f"/api/assets/{source.id}/relations",
        json={"relation_type": "depends_on", "target_id": str(uuid4())},
    )
    assert r_hidden.status_code == r_missing.status_code == 404
    assert r_hidden.json()["code"] == "asset_not_found"
    assert r_hidden.content == r_missing.content
    r_slug = await client.post(
        f"/api/assets/{source.id}/relations",
        json={"relation_type": "depends_on", "target_slug": hidden.slug},
    )
    assert r_slug.content == r_missing.content


@pytest.mark.asyncio
async def test_superseded_other_end_patch_and_delete(client, session):
    owner, _m, _v, a, b, _c = await _seed(session)
    await login_as(client, owner)

    r = await _add(client, a, b, "supersedes", note="v2")
    assert r.status_code == 201
    created = r.json()
    assert created["origin"] == "manual"
    assert created["target_version"] == created["target_version_now"] == 1

    r = await client.get(f"/api/assets/by-slug/{a.slug}/relations?types=supersedes&direction=out")
    (edge,) = r.json()["outgoing"]["supersedes"]
    assert edge["other"]["freshness"] == "superseded"
    assert r.json()["incoming"] == {}

    r = await _add(client, a, b, "blocks")
    assert r.status_code == 400
    assert r.json()["code"] == "relation_type_invalid"
    r = await _add(client, b, a, "supersedes")
    assert r.status_code == 409
    assert r.json()["code"] == "relation_cycle"

    r = await client.patch(f"/api/relations/{created['id']}", json={"note": None})
    assert r.status_code == 200
    assert r.json()["note"] is None

    r = await client.delete(f"/api/relations/{created['id']}")
    assert r.status_code == 200
    r = await client.delete(f"/api/relations/{created['id']}")
    assert r.status_code == 404
    assert r.json()["code"] == "relation_not_found"


@pytest.mark.asyncio
async def test_symmetric_edge_is_listed_from_both_ends(client, session):
    owner, _m, _v, a, b, _c = await _seed(session)
    await login_as(client, owner)
    assert (await _add(client, b, a, "contradicts")).status_code == 201
    for asset, other in ((a, b), (b, a)):
        r = await client.get(f"/api/assets/by-slug/{asset.slug}/relations")
        (edge,) = r.json()["outgoing"]["contradicts"]
        assert edge["other"]["slug"] == other.slug
        r = await client.get(f"/api/assets/by-slug/{asset.slug}/relations?direction=in")
        assert [e["other"]["slug"] for e in r.json()["incoming"]["contradicts"]] == [other.slug]


@pytest.mark.asyncio
async def test_single_relation_in_compact_shape_and_write_responses(client, session):
    owner, member, share_viewer, a, b, _c = await _seed(session)
    await login_as(client, owner)
    full = await _add(client, a, b)
    assert full.status_code == 201
    assert full.json()["source_id"] == str(a.id)  # the default stays the full shape

    r = await client.post(
        f"/api/assets/{b.id}/relations",
        params={"shape": "compact"},
        json={"relation_type": "derived_from", "target_id": str(a.id), "note": "basis"},
    )
    assert r.status_code == 201
    created = r.json()
    edge_id = created["edge"][3]["id"]
    assert created["edge"] == [b.slug, "derived_from", a.slug, {"id": edge_id, "note": "basis"}]
    assert list(created["nodes"]) == [b.slug, a.slug]
    assert created["nodes"][a.slug]["title"] == "A"
    assert "summary" not in created["nodes"][a.slug]

    r = await client.patch(
        f"/api/relations/{edge_id}", params={"shape": "compact"}, json={"note": "new basis"}
    )
    assert r.status_code == 200
    assert r.json()["edge"][3] == {"id": edge_id, "note": "new basis"}

    # A project viewer has graph access to both ends.
    await login_as(client, member)
    r = await client.get(f"/api/relations/{edge_id}")
    assert r.status_code == 200
    assert r.json() == {
        **created,
        "edge": [*created["edge"][:3], {"id": edge_id, "note": "new basis"}],
    }

    # A direct viewer share gives no graph access: the same 404 as a missing edge.
    missing = await client.get(f"/api/relations/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "relation_not_found"
    await login_as(client, share_viewer)
    r = await client.get(f"/api/relations/{edge_id}")
    assert (r.status_code, r.json()) == (404, missing.json())


@pytest.mark.asyncio
async def test_single_relation_with_hidden_end_is_not_found(client, session):
    owner, member, _v, a, _b, c = await _seed(session)
    await login_as(client, owner)
    r = await _add(client, a, c)
    edge_id = r.json()["id"]
    assert (await client.get(f"/api/relations/{edge_id}")).status_code == 200

    await login_as(client, member)
    r = await client.get(f"/api/relations/{edge_id}")
    missing = await client.get(f"/api/relations/{uuid4()}")
    assert r.status_code == 404
    assert r.json() == missing.json()
    assert c.slug not in r.text
