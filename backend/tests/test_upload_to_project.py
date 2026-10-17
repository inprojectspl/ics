"""Upload-to-project: POST /api/assets?project_id=… assigns the new asset
to a project in one shot.

Gate is `permissions.assert_project_contributor` (owner/editor member or
sys-admin). Viewers and non-members get 403; a missing project 404. The
membership check runs *before* any storage write, so a rejected upload
leaves no orphan blob.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import Asset, Project, ProjectMember, User
from app.slug import generate_slug
from tests.conftest import login_as as _login
from tests.conftest import mk_user


def _md_file(name: str = "doc.md", content: bytes = b"# Hello") -> tuple[str, bytes, str]:
    return (name, content, "text/markdown")


async def _mk_member_project(session, user: User, role: str) -> Project:
    """Project with `user` as an accepted member at `role`."""
    project = Project(slug=generate_slug(10), name="Proj", created_by=user.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=user.id,
            role=role,
            invited_by=user.id,
            accepted_at=datetime.now(tz=UTC),
        )
    )
    await session.commit()
    return project


async def _project_id_of(session, slug: str) -> str | None:
    asset = (await session.execute(select(Asset).where(Asset.slug == slug))).scalar_one()
    return str(asset.project_id) if asset.project_id else None


@pytest.mark.asyncio
async def test_upload_markdown_into_project_as_owner(client, session, fs_storage):
    user = await mk_user(session)
    project = await _mk_member_project(session, user, "owner")
    await _login(client, user)

    r = await client.post(f"/api/assets?project_id={project.id}", files={"file": _md_file()})
    assert r.status_code == 201, r.text
    assert await _project_id_of(session, r.json()["slug"]) == str(project.id)


@pytest.mark.asyncio
async def test_upload_markdown_into_project_as_editor(client, session, fs_storage):
    user = await mk_user(session)
    project = await _mk_member_project(session, user, "editor")
    await _login(client, user)

    r = await client.post(f"/api/assets?project_id={project.id}", files={"file": _md_file()})
    assert r.status_code == 201, r.text
    assert await _project_id_of(session, r.json()["slug"]) == str(project.id)


@pytest.mark.asyncio
async def test_upload_markdown_into_project_as_viewer_forbidden(client, session, fs_storage):
    user = await mk_user(session)
    project = await _mk_member_project(session, user, "viewer")
    await _login(client, user)

    r = await client.post(f"/api/assets?project_id={project.id}", files={"file": _md_file()})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_upload_markdown_into_project_non_member_forbidden(client, session, fs_storage):
    owner = await mk_user(session)
    project = await _mk_member_project(session, owner, "owner")
    stranger = await mk_user(session)
    await session.commit()
    await _login(client, stranger)

    r = await client.post(f"/api/assets?project_id={project.id}", files={"file": _md_file()})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_upload_markdown_into_missing_project_404(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post(f"/api/assets?project_id={uuid4()}", files={"file": _md_file()})
    assert r.status_code == 404
    # Rejected before any asset row, so no orphan is persisted.
    leftover = (
        (await session.execute(select(Asset).where(Asset.owner_id == user.id))).scalars().all()
    )
    assert leftover == []


@pytest.mark.asyncio
async def test_upload_collection_into_project_as_editor(client, session, fs_storage):
    import io

    user = await mk_user(session)
    project = await _mk_member_project(session, user, "editor")
    await _login(client, user)

    files = [
        ("files", ("a.md", io.BytesIO(b"# A\n[[b]]"), "text/markdown")),
        ("files", ("b.md", io.BytesIO(b"# B"), "text/markdown")),
    ]
    r = await client.post(
        f"/api/assets/collection?project_id={project.id}",
        files=files,
        data={"paths": ["a.md", "b.md"]},
    )
    assert r.status_code == 201, r.text
    assert await _project_id_of(session, r.json()["slug"]) == str(project.id)


@pytest.mark.asyncio
async def test_upload_without_project_id_stays_personal(client, session, fs_storage):
    user = await mk_user(session)
    await session.commit()
    await _login(client, user)

    r = await client.post("/api/assets", files={"file": _md_file()})
    assert r.status_code == 201, r.text
    assert await _project_id_of(session, r.json()["slug"]) is None
