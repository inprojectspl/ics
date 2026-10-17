"""`GET /api/assets/by-slug/{slug}/summary`: a single AssetSummary row for the
management panel in the reader.

The endpoint is editor+ because the panel is editor+: a read-only reader must
get neither the actions nor the metadata that feed them (active share modes,
GitLab binding state).
"""

from __future__ import annotations

import pytest

from app.models import AssetPin, AssetShare, Project, ProjectMember, ShareLink
from app.slug import generate_slug, generate_token
from app.util import now as utc_now
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user, put_blob

MD = b"# Title\n\nBody.\n"


async def _mk_md_single(session, owner, **kw):
    asset = await mk_asset(session, owner, kind="md_single", entry_path="doc.md", **kw)
    await put_blob(asset, "doc.md", MD)
    return asset


@pytest.mark.asyncio
async def test_owner_gets_row_with_management_metadata(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _mk_md_single(session, owner, title="Report")
    project = Project(name="Project", slug=generate_slug(), created_by=owner.id)
    session.add(project)
    await session.flush()
    asset.project_id = project.id
    session.add(ShareLink(asset_id=asset.id, token=generate_token(), mode="public"))
    session.add(AssetPin(asset_id=asset.id, user_id=owner.id))
    await session.commit()
    await _login(client, owner)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(asset.id)
    assert body["slug"] == asset.slug
    assert body["title"] == "Report"
    assert body["my_role"] == "owner"
    assert body["project_id"] == str(project.id)
    assert body["active_share_modes"] == ["public"]
    assert body["pinned_at"] is not None


@pytest.mark.asyncio
async def test_editor_share_gets_row(client, session, fs_storage):
    owner = await mk_user(session)
    editor = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=editor.id, role="editor"))
    await session.commit()
    await _login(client, editor)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/summary")
    assert r.status_code == 200
    assert r.json()["my_role"] == "editor"


@pytest.mark.asyncio
async def test_read_only_viewer_is_404(client, session, fs_storage):
    """A reader sees the document, but not the management panel or its data."""
    owner = await mk_user(session)
    reader = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=reader.id, role="viewer"))
    await session.commit()
    await _login(client, reader)

    assert (await client.get(f"/api/assets/by-slug/{asset.slug}/doc")).status_code == 200
    r = await client.get(f"/api/assets/by-slug/{asset.slug}/summary")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_project_observer_is_404(client, session, fs_storage):
    owner = await mk_user(session)
    observer = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    project = Project(name="P", slug=generate_slug(), created_by=owner.id)
    session.add(project)
    await session.flush()
    asset.project_id = project.id
    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=observer.id,
            role="viewer",
            accepted_at=utc_now(),
        )
    )
    await session.commit()
    await _login(client, observer)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/summary")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_stranger_is_404(client, session, fs_storage):
    owner = await mk_user(session)
    stranger = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    await session.commit()
    await _login(client, stranger)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/summary")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_anonymous_is_rejected(client, session, fs_storage):
    owner = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    await session.commit()

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/summary")
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_pin_state_is_per_caller(client, session, fs_storage):
    """`pinned_at` comes from the caller's pins, not the owner's."""
    owner = await mk_user(session)
    editor = await mk_user(session)
    asset = await _mk_md_single(session, owner)
    session.add(AssetShare(asset_id=asset.id, user_id=editor.id, role="editor"))
    session.add(AssetPin(asset_id=asset.id, user_id=owner.id))
    await session.commit()
    await _login(client, editor)

    r = await client.get(f"/api/assets/by-slug/{asset.slug}/summary")
    assert r.status_code == 200
    assert r.json()["pinned_at"] is None
