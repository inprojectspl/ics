"""The audit log names and links what its references point at (services/audit_labels)."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app import audit
from app.models import GitLabBinding, Project, ShareLink
from app.services.audit_labels import RefInfo, payload_refs, resolve_refs
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_user


@pytest.mark.asyncio
async def test_resolves_names_and_app_links(session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, title="Handbook")
    gone = await mk_asset(session, owner, title="Old")
    gone.deleted_at = datetime.now(UTC)
    project = Project(slug=generate_slug(10), name="Portal", created_by=owner.id)
    share = ShareLink(
        asset_id=asset.id, token=generate_slug(20), mode="public", created_by=owner.id
    )
    binding = GitLabBinding(asset_id=asset.id, public_key="pk", created_by=owner.id)
    session.add_all([project, share, binding])
    await session.flush()

    refs = await resolve_refs(
        session,
        [
            f"asset:{asset.id}",
            f"asset:{gone.id}",
            f"user_id:{owner.id}",
            f"user:{owner.email}",
            f"project:{project.id}",
            f"share:{share.id}",
            f"binding:{binding.id}",
            "cdn:cdn.example.com",
            f"asset:{uuid4()}",  # row is gone
            "asset:not-a-uuid",
            None,
        ],
    )
    users = f"/admin/users?user={owner.id}"
    assert refs == {
        f"asset:{asset.id}": RefInfo("Handbook", f"/v/{asset.slug}"),
        f"asset:{gone.id}": RefInfo("Old", None),  # deleted: named, not linked
        f"user_id:{owner.id}": RefInfo(owner.email, users),
        f"user:{owner.email}": RefInfo(owner.email, users),
        f"project:{project.id}": RefInfo("Portal", f"/projects/{project.slug}"),
        f"share:{share.id}": RefInfo("Handbook", f"/v/{asset.slug}"),
        f"binding:{binding.id}": RefInfo("Handbook", f"/v/{asset.slug}"),
        "cdn:cdn.example.com": RefInfo("cdn.example.com", "/admin/cdn"),
    }


@pytest.mark.asyncio
async def test_audit_list_carries_names_and_links(session, client):
    admin = await mk_user(session, role="admin")
    asset = await mk_asset(session, admin, title="Runbook")
    await audit.record(session, actor=admin, action="asset_renamed", target=f"asset:{asset.id}")
    await session.commit()
    await login_as(client, admin)

    r = await client.get(
        "/api/admin/audit", params={"action": "asset_renamed", "target": f"asset:{asset.id}"}
    )
    assert r.status_code == 200
    [row] = r.json()["items"]
    assert (row["target_label"], row["target_href"]) == ("Runbook", f"/v/{asset.slug}")
    assert (row["actor_label"], row["actor_href"]) == (admin.email, f"/admin/users?user={admin.id}")


def test_payload_refs_follow_the_field_and_the_action():
    pid, aid = uuid4(), uuid4()
    assert payload_refs("asset_project_changed", {"to": str(pid), "from": None}) == {
        "to": [f"project:{pid}"]
    }
    # Elsewhere `to` is a task key, not a project.
    assert payload_refs("external_refs_rekeyed", {"to": "openproject:12"}) == {}
    assert payload_refs("project_key_documents_set", {"assets": [str(aid)]}) == {
        "assets": [f"asset:{aid}"]
    }
    assert payload_refs("login_ok", None) == {}


@pytest.mark.asyncio
async def test_audit_list_names_projects_in_the_payload(session, client):
    admin = await mk_user(session, role="admin")
    asset = await mk_asset(session, admin, title="Contract")
    project = Project(slug=generate_slug(10), name="Legal department", created_by=admin.id)
    session.add(project)
    await session.flush()
    await audit.record(
        session,
        actor=admin,
        action="asset_project_changed",
        target=f"asset:{asset.id}",
        payload={"to": str(project.id), "from": None},
    )
    await session.commit()
    await login_as(client, admin)

    r = await client.get(
        "/api/admin/audit",
        params={"action": "asset_project_changed", "target": f"asset:{asset.id}"},
    )
    [row] = r.json()["items"]
    assert row["payload_refs"] == {
        "to": [{"label": "Legal department", "href": f"/projects/{project.slug}"}]
    }


@pytest.mark.asyncio
async def test_binding_events_name_the_document_and_hold_bare_key_tails(session, client):
    from sqlalchemy import select

    from app.models import AuditLog

    owner = await mk_user(session, role="admin")
    asset = await mk_asset(session, owner, title="Pipeline doc")
    await session.commit()
    await login_as(client, owner)
    created = (await client.post("/api/bindings", json={"asset_id": str(asset.id)})).json()
    assert (await client.post(f"/api/bindings/{created['id']}/rotate")).status_code == 200
    assert (await client.delete(f"/api/bindings/{created['id']}")).status_code == 204

    rotated = (
        await session.execute(
            select(AuditLog).where(
                AuditLog.action == "binding_rotated",
                AuditLog.target == f"binding:{created['id']}",
            )
        )
    ).scalar_one()
    for key in ("old_key_tail", "new_key_tail"):
        tail = rotated.payload[key]
        assert tail and "-" not in tail and "\n" not in tail
    assert rotated.payload["old_key_tail"] in created["public_key"].replace("\n", "")

    r = await client.get(
        "/api/admin/audit",
        params={"action": "binding_deleted", "target": f"binding:{created['id']}"},
    )
    [row] = r.json()["items"]
    assert row["payload_refs"]["asset_id"] == [
        {"label": "Pipeline doc", "href": f"/v/{asset.slug}"}
    ]
