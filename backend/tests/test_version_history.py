"""Version history: who updated the file and when.

Two surfaces, two disclosure thresholds:
- `GET /api/assets/{id}/versions`: viewer-level, but `storage_prefix` and the
  author's full e-mail only for editor+,
- `GET /api/share/{token}/versions`: behind the link-mode gate, the author
  always without the e-mail domain (a `public` link ends up on the internet).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import AssetVersion, Project, ProjectMember, ShareLink
from app.services.versions import author_label
from app.slug import generate_slug, generate_token
from tests.conftest import login_as as _login
from tests.conftest import mk_asset, mk_user


async def _with_history(session, owner, author):
    asset = await mk_asset(session, owner)
    asset.version = 2
    session.add_all(
        [
            AssetVersion(
                asset_id=asset.id,
                version=1,
                storage_prefix=f"{asset.storage_prefix}/v1",
                size_bytes=100,
                created_by=owner.id,
                created_at=datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
            ),
            AssetVersion(
                asset_id=asset.id,
                version=2,
                storage_prefix=f"{asset.storage_prefix}/v2",
                size_bytes=200,
                created_by=author.id,
                created_at=datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
            ),
        ]
    )
    await session.commit()
    return asset


def test_author_label_prefers_display_name():
    assert author_label("Jane Doe", "j.d@example.com") == "Jane Doe"


def test_author_label_falls_back_to_local_part_without_domain():
    label = author_label(None, "jane.doe@example.com")
    assert label == "jane.doe"
    assert "@" not in label


def test_author_label_handles_deleted_user():
    assert author_label(None, None) is None


@pytest.mark.asyncio
async def test_owner_sees_authors_and_storage_prefix(client, session):
    owner = await mk_user(session, display_name="Owner Name")
    editor = await mk_user(session, display_name="Editor Name")
    asset = await _with_history(session, owner, editor)
    await _login(client, owner)

    r = await client.get(f"/api/assets/{asset.id}/versions")
    assert r.status_code == 200
    rows = r.json()
    assert [v["version"] for v in rows] == [2, 1]
    assert rows[0]["author"] == "Editor Name"
    assert rows[0]["author_email"] == editor.email
    assert rows[0]["storage_prefix"] is not None
    assert rows[0]["is_current"] is True
    assert rows[1]["is_current"] is False


@pytest.mark.asyncio
async def test_project_viewer_can_read_history_without_internals(client, session):
    """A read-only collaborator sees the file in the list and can open a
    version preview, so the history must be available to them, but without
    the storage path and the author's full e-mail."""
    owner = await mk_user(session)
    observer = await mk_user(session)
    project = Project(slug=generate_slug(8), name="P", created_by=owner.id)
    session.add(project)
    await session.flush()
    asset = await _with_history(session, owner, owner)
    asset.project_id = project.id
    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=observer.id,
            role="viewer",
            accepted_at=datetime.now(UTC),
        )
    )
    await session.commit()
    await _login(client, observer)

    r = await client.get(f"/api/assets/{asset.id}/versions")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert all(v["storage_prefix"] is None for v in rows)
    assert all(v["author_email"] is None for v in rows)
    assert rows[0]["author"] is not None


@pytest.mark.asyncio
async def test_stranger_gets_404_on_history(client, session):
    owner = await mk_user(session)
    outsider = await mk_user(session)
    asset = await _with_history(session, owner, owner)
    await _login(client, outsider)

    r = await client.get(f"/api/assets/{asset.id}/versions")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_share_versions_lists_history_without_emails(client, session):
    owner = await mk_user(session, display_name="Change Author")
    asset = await _with_history(session, owner, owner)
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="public",
        created_by=owner.id,
    )
    session.add(share)
    await session.commit()
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{share.token}/versions")
    assert r.status_code == 200
    rows = r.json()
    # Same shape as the owner-side `/versions`: the client counts versions
    # from the list length and reads `current_version` from the `is_current` flag.
    assert len(rows) == 2
    assert [v["version"] for v in rows] == [2, 1]
    assert rows[0]["is_current"] is True
    assert rows[0]["author"] == "Change Author"
    assert all(v["author_email"] is None for v in rows)
    assert all(v["storage_prefix"] is None for v in rows)


@pytest.mark.asyncio
async def test_share_versions_does_not_burn_views(client, session):
    owner = await mk_user(session)
    asset = await _with_history(session, owner, owner)
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="public",
        created_by=owner.id,
        max_views=1,
    )
    session.add(share)
    await session.commit()
    await client.post("/api/auth/logout")

    assert (await client.get(f"/api/share/{share.token}/versions")).status_code == 200
    await session.refresh(share)
    assert share.view_count == 0


@pytest.mark.asyncio
async def test_share_versions_requires_password_gate(client, session):
    owner = await mk_user(session)
    asset = await _with_history(session, owner, owner)
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="password",
        created_by=owner.id,
        password_hash="$2b$12$notarealhash",
    )
    session.add(share)
    await session.commit()
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{share.token}/versions")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_share_versions_dead_link_is_410(client, session):
    owner = await mk_user(session)
    asset = await _with_history(session, owner, owner)
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode="public",
        created_by=owner.id,
        max_views=1,
        view_count=1,
    )
    session.add(share)
    await session.commit()
    await client.post("/api/auth/logout")

    r = await client.get(f"/api/share/{share.token}/versions")
    assert r.status_code == 410
