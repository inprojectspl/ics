"""Project links (ADR-0018): one ICS home per OpenProject project, a 409 that
does not name the holder, a by-external lookup that hides non-members, and
ordered key documents."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import AuditLog, Project, ProjectMember
from app.slug import generate_slug
from tests.conftest import login_as, mk_asset, mk_user


async def _project(session, owner, **members) -> Project:
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
    await session.commit()
    return project


def _op(identifier: str) -> dict:
    return {"refs": [{"system": "openproject", "external_id": identifier}]}


@pytest.mark.asyncio
async def test_taken_identifier_is_409_without_the_holder(client, session):
    alice = await mk_user(session)
    first = await _project(session, alice)
    second = await _project(session, alice)
    identifier = f"acme-{generate_slug(6).lower()}"
    await login_as(client, alice)

    r = await client.put(f"/api/projects/{first.slug}/external-refs", json=_op(identifier))
    assert r.status_code == 200
    assert r.json() == [{"system": "openproject", "external_id": identifier}]

    r = await client.put(f"/api/projects/{second.slug}/external-refs", json=_op(identifier))
    assert r.status_code == 409
    assert r.json()["code"] == "project_external_taken"
    assert first.slug not in r.text
    assert str(first.id) not in r.text
    assert first.name not in r.text

    # Re-sending the same mapping to its home is not a conflict.
    r = await client.put(f"/api/projects/{first.slug}/external-refs", json=_op(identifier))
    assert r.status_code == 200
    actions = (
        await session.scalars(
            select(AuditLog.action).where(AuditLog.target == f"project:{first.id}")
        )
    ).all()
    assert actions.count("project_external_ref_set") == 1


@pytest.mark.asyncio
async def test_by_external_hides_project_from_non_members(client, session):
    owner = await mk_user(session)
    viewer = await mk_user(session)
    stranger = await mk_user(session)
    project = await _project(session, owner, viewer=[viewer])
    identifier = f"ops-{generate_slug(6).lower()}"
    await login_as(client, owner)
    await client.put(f"/api/projects/{project.slug}/external-refs", json=_op(identifier))

    url = "/api/projects/by-external?system=openproject&id="
    await login_as(client, viewer)
    r = await client.get(url + identifier)
    assert r.status_code == 200
    assert r.json()["slug"] == project.slug
    assert r.json()["my_role"] == "viewer"
    # Members read the mapping, only the owner changes it.
    assert (await client.get(f"/api/projects/{project.slug}/external-refs")).status_code == 200
    r = await client.put(f"/api/projects/{project.slug}/external-refs", json={"refs": []})
    assert r.status_code == 403

    await login_as(client, stranger)
    hidden = await client.get(url + identifier)
    missing = await client.get(url + "no-such-project")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


@pytest.mark.asyncio
async def test_deleted_project_releases_its_identifier(client, session):
    owner = await mk_user(session)
    old = await _project(session, owner)
    new = await _project(session, owner)
    identifier = f"old-{generate_slug(6).lower()}"
    await login_as(client, owner)
    await client.put(f"/api/projects/{old.slug}/external-refs", json=_op(identifier))
    assert (await client.delete(f"/api/projects/{old.slug}")).status_code == 200
    r = await client.put(f"/api/projects/{new.slug}/external-refs", json=_op(identifier))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_key_document_order_persists(client, session):
    owner = await mk_user(session)
    member = await mk_user(session)
    project = await _project(session, owner, viewer=[member])
    docs = [await mk_asset(session, owner, title=f"doc {i}") for i in range(3)]
    for d in docs[:2]:
        d.project_id = project.id
    # The third is the owner's private file: allowed, but hidden from members.
    other = await mk_user(session)
    foreign = await mk_asset(session, other)
    await session.commit()
    await login_as(client, owner)

    body = {
        "documents": [
            {"asset_id": str(docs[2].id), "reason": "glossary"},
            {"asset_id": str(docs[0].id), "reason": "charter"},
            {"asset_id": str(docs[1].id)},
        ]
    }
    r = await client.put(f"/api/projects/{project.slug}/key-documents", json=body)
    assert r.status_code == 200
    r = await client.get(f"/api/projects/{project.slug}/key-documents")
    assert [(d["slug"], d["reason"]) for d in r.json()] == [
        (docs[2].slug, "glossary"),
        (docs[0].slug, "charter"),
        (docs[1].slug, None),
    ]

    await login_as(client, member)
    r = await client.get(f"/api/projects/{project.slug}/key-documents")
    assert [d["slug"] for d in r.json()] == [docs[0].slug, docs[1].slug]

    await login_as(client, owner)
    r = await client.put(
        f"/api/projects/{project.slug}/key-documents",
        json={"documents": [{"asset_id": str(foreign.id)}]},
    )
    assert r.status_code == 404
    assert r.json()["code"] == "asset_not_found"
    r = await client.get(f"/api/projects/{project.slug}/key-documents")
    assert len(r.json()) == 3
