"""POST /api/assets/html-json applies the same gates as the multipart uploads:
project contributor check, tag validation and the default share link.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.models import Asset, Project, ProjectMember, ShareLink, User
from app.slug import generate_slug
from tests.conftest import login_as, mk_user

_FILES = [{"path": "index.html", "content_text": "<!doctype html><body>hi</body>"}]


def _body(**extra) -> dict:
    return {"title": "Bundle", "entry_path": "index.html", "files": _FILES, **extra}


async def _mk_project(session, owner: User, member: User | None = None, role: str = "viewer"):
    project = Project(slug=generate_slug(), name="P", created_by=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(
            project_id=project.id, user_id=owner.id, role="owner", accepted_at=datetime.now(UTC)
        )
    )
    if member is not None:
        session.add(
            ProjectMember(
                project_id=project.id, user_id=member.id, role=role, accepted_at=datetime.now(UTC)
            )
        )
    await session.commit()
    return project


async def _asset_count(session, owner: User) -> int:
    return (
        await session.execute(select(func.count()).where(Asset.owner_id == owner.id))
    ).scalar_one()


@pytest.mark.asyncio
async def test_project_non_member_is_refused(client, session, fs_storage):
    owner = await mk_user(session)
    outsider = await mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner)
    await login_as(client, outsider)

    r = await client.post("/api/assets/html-json", json=_body(project_id=str(project.id)))

    assert r.status_code == 403
    assert r.json()["code"] == "project_role_required"
    assert await _asset_count(session, outsider) == 0


@pytest.mark.asyncio
async def test_project_viewer_is_refused(client, session, fs_storage):
    owner = await mk_user(session)
    viewer = await mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner, viewer, role="viewer")
    await login_as(client, viewer)

    r = await client.post("/api/assets/html-json", json=_body(project_id=str(project.id)))

    assert r.status_code == 403
    assert r.json()["code"] == "project_role_required"
    assert await _asset_count(session, viewer) == 0


@pytest.mark.asyncio
async def test_project_unknown_is_404(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post("/api/assets/html-json", json=_body(project_id=str(uuid4())))

    assert r.status_code == 404
    assert r.json()["code"] == "project_not_found"
    assert await _asset_count(session, user) == 0


@pytest.mark.asyncio
async def test_project_editor_can_upload(client, session, fs_storage):
    owner = await mk_user(session)
    editor = await mk_user(session)
    await session.commit()
    project = await _mk_project(session, owner, editor, role="editor")
    await login_as(client, editor)

    r = await client.post("/api/assets/html-json", json=_body(project_id=str(project.id)))

    assert r.status_code == 201, r.text
    asset = await session.get(Asset, r.json()["id"])
    assert asset is not None
    assert asset.project_id == project.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tags",
    [["Any Label!"], ["a"], [f"tag-{i:02d}" for i in range(21)]],
    ids=["tags_invalid_chars", "tags_too_short", "tags_too_many"],
)
async def test_tags_invalid_are_rejected(client, session, fs_storage, tags):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post("/api/assets/html-json", json=_body(tags=tags))

    assert r.status_code == 422
    assert await _asset_count(session, user) == 0


@pytest.mark.asyncio
async def test_tags_are_normalized(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post("/api/assets/html-json", json=_body(tags=["Report", "report", "q3"]))

    assert r.status_code == 201, r.text
    asset = await session.get(Asset, r.json()["id"])
    assert asset is not None
    assert asset.tags == ["report", "q3"]


async def _links(session, asset_id) -> list[ShareLink]:
    return list(
        (await session.execute(select(ShareLink).where(ShareLink.asset_id == asset_id)))
        .scalars()
        .all()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["org_sso", "public"])
async def test_share_mode_creates_link(client, session, fs_storage, mode):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post("/api/assets/html-json", json=_body(share_mode=mode))

    assert r.status_code == 201, r.text
    links = await _links(session, r.json()["id"])
    assert [(link.mode, link.revoked_at) for link in links] == [(mode, None)]


@pytest.mark.asyncio
async def test_share_mode_omitted_defaults_to_org_sso(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post("/api/assets/html-json", json=_body(share_mode=None))

    assert r.status_code == 201, r.text
    links = await _links(session, r.json()["id"])
    assert [link.mode for link in links] == ["org_sso"]


@pytest.mark.asyncio
async def test_share_mode_skipped_for_critical_bundle(client, session, fs_storage, monkeypatch):
    from app.services import asset_security

    monkeypatch.setattr(asset_security, "publication_blocked", lambda _asset: True)
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)

    r = await client.post("/api/assets/html-json", json=_body(share_mode="public"))

    assert r.status_code == 201, r.text
    assert await _links(session, r.json()["id"]) == []
