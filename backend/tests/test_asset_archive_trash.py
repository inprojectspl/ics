"""Archive and trash of assets (ADR-0029): who may use them, what lists and
search show, restore and the purge with files."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Asset, AuditLog, Project, ProjectMember, ShareLink
from app.services import asset_lifecycle
from app.slug import generate_slug, generate_token
from app.storage import storage_from_url
from tests.conftest import login_as, mk_admin, mk_asset, mk_user, put_blob


@pytest.fixture(autouse=True)
def _no_outline_jobs(monkeypatch):
    async def enqueue(*args, **kwargs):
        return None

    monkeypatch.setattr("app.routes.mcp_assets.lifecycle.enqueue", enqueue)


async def _project(session, owner, *members):
    project = Project(slug=generate_slug(10), name="Proj", created_by=owner.id)
    session.add(project)
    await session.flush()
    for user, role in ((owner, "owner"), *members):
        session.add(
            ProjectMember(
                project_id=project.id,
                user_id=user.id,
                role=role,
                invited_by=owner.id,
                accepted_at=datetime.now(UTC),
            )
        )
    await session.flush()
    return project


async def _slugs(client, *params: tuple[str, str]) -> set[str]:
    r = await client.get("/api/assets", params=[("page_size", "200"), *params])
    assert r.status_code == 200, r.text
    return {item["slug"] for item in r.json()["items"]}


# ---------- archive ----------


@pytest.mark.asyncio
async def test_archive_leaves_lists_but_still_opens(client, session):
    user = await mk_user(session)
    kept = await mk_asset(session, user, title="Kept")
    gone = await mk_asset(session, user, title="Archived one")
    await session.commit()
    await login_as(client, user)

    r = await client.post(f"/api/assets/{gone.id}/archive")
    assert r.status_code == 200, r.text
    assert r.json()["noop"] is False and r.json()["archived_at"]

    assert await _slugs(client) == {kept.slug}
    assert await _slugs(client, ("f", "archive:archived")) == {gone.slug}
    assert await _slugs(client, ("f", "archive:archived"), ("f", "archive:active")) == {
        kept.slug,
        gone.slug,
    }
    # Opened by slug as before, marked as archived.
    meta = await client.get(f"/api/assets/by-slug/{gone.slug}/meta")
    assert meta.status_code == 200
    assert meta.json()["archived_at"]


@pytest.mark.asyncio
async def test_archive_facet_and_scope_counts(client, session):
    user = await mk_user(session)
    await mk_asset(session, user)
    archived = await mk_asset(session, user)
    archived.archived_at = datetime.now(UTC)
    await session.commit()
    await login_as(client, user)

    body = (await client.get("/api/assets", params={"facets": "true"})).json()
    assert body["total"] == 1
    assert body["scope_counts"]["state:mine"] == 1
    assert body["filter_counts"]["archive:archived"] == 1
    assert "state:trash" not in body["scope_counts"]


@pytest.mark.asyncio
async def test_archive_is_idempotent_and_reversible(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    await login_as(client, user)

    await client.post(f"/api/assets/{asset.id}/archive")
    again = await client.post(f"/api/assets/{asset.id}/archive")
    assert again.json()["noop"] is True
    back = await client.delete(f"/api/assets/{asset.id}/archive")
    assert back.status_code == 200 and back.json()["archived_at"] is None
    await session.refresh(asset)
    assert asset.archived_at is None and asset.archived_by is None
    actions = (
        await session.scalars(select(AuditLog.action).where(AuditLog.target == f"asset:{asset.id}"))
    ).all()
    assert actions.count("asset_archived") == 1 and "asset_unarchived" in actions


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "allowed"), [("owner", True), ("editor", False), ("viewer", False)]
)
async def test_archive_needs_a_manager(client, session, role, allowed):
    author = await mk_user(session)
    member = await mk_user(session)
    asset = await mk_asset(session, author)
    project = await _project(session, member, (author, "editor")) if role == "owner" else None
    if project is None:
        project = await _project(session, author, (member, role))
    asset.project_id = project.id
    await session.commit()
    await login_as(client, member)

    r = await client.post(f"/api/assets/{asset.id}/archive")
    assert (r.status_code == 200) is allowed
    if not allowed:
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_project_page_and_counts_leave_the_archive_out(client, session):
    user = await mk_user(session)
    project = await _project(session, user)
    live = await mk_asset(session, user)
    archived = await mk_asset(session, user)
    for a in (live, archived):
        a.project_id = project.id
    archived.archived_at = datetime.now(UTC)
    await session.commit()
    await login_as(client, user)

    page = (await client.get(f"/api/projects/{project.slug}")).json()
    assert [a["slug"] for a in page["assets"]] == [live.slug]
    assert page["asset_count"] == 1 and page["archived_count"] == 1
    only = (
        await client.get(f"/api/projects/{project.slug}", params={"archive": "archived"})
    ).json()
    assert [a["slug"] for a in only["assets"]] == [archived.slug]
    assert only["asset_count"] == 1
    listed = (await client.get("/api/projects")).json()
    row = next(p for p in listed["items"] if p["slug"] == project.slug)
    assert row["asset_count"] == 1


@pytest.mark.asyncio
async def test_mcp_index_and_search_take_the_archive_view(client, session):
    user = await mk_user(session)
    live = await mk_asset(session, user, title="Zebra live")
    archived = await mk_asset(session, user, title="Zebra old")
    archived.archived_at = datetime.now(UTC)
    await session.commit()
    await login_as(client, user)

    async def index(**params):
        r = await client.get("/api/assets/index", params=params)
        assert r.status_code == 200, r.text
        return {i["slug"] for i in r.json()["items"]}

    assert await index() == {live.slug}
    assert await index(archive="archived") == {archived.slug}
    assert await index(archive="all") == {live.slug, archived.slug}

    async def search(**params):
        r = await client.get("/api/assets/search-mcp", params={"q": "zebra", **params})
        assert r.status_code == 200, r.text
        return {h["slug"] for h in r.json()["items"]}

    assert await search() == {live.slug}
    assert await search(archive="all") == {live.slug, archived.slug}
    hits = (
        await client.get("/api/assets/search-mcp", params={"q": "zebra", "archive": "archived"})
    ).json()["items"]
    assert [h["archived"] for h in hits] == [True]


# ---------- trash ----------


@pytest.mark.asyncio
async def test_delete_moves_to_trash_with_purge_date(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    session.add(
        ShareLink(asset_id=asset.id, token=generate_token(), mode="public", created_by=user.id)
    )
    await session.commit()
    await login_as(client, user)

    assert (await client.delete(f"/api/assets/{asset.id}")).status_code == 204
    await session.refresh(asset)
    assert asset.deleted_by == user.id
    expected = asset.deleted_at + timedelta(days=get_settings().trash_retention_days)
    assert asset.purge_at == expected
    link = await session.scalar(select(ShareLink).where(ShareLink.asset_id == asset.id))
    assert link is not None and link.revoked_at is not None

    assert await _slugs(client) == set()
    trash = (await client.get("/api/assets", params={"scope": "state:trash"})).json()
    [row] = trash["items"]
    assert row["slug"] == asset.slug
    assert row["deleted_by"]["id"] == str(user.id)
    assert row["purge_at"] == expected.isoformat()


@pytest.mark.asyncio
async def test_project_owner_sees_and_restores_the_project_trash(client, session):
    author = await mk_user(session)
    owner = await mk_user(session)
    stranger = await mk_user(session)
    project = await _project(session, owner, (author, "editor"))
    asset = await mk_asset(session, author)
    asset.project_id = project.id
    asset.deleted_at = datetime.now(UTC)
    asset.deleted_by = author.id
    await session.commit()

    await login_as(client, stranger)
    trash = (await client.get("/api/assets", params={"scope": "state:trash"})).json()
    assert trash["items"] == []
    assert (await client.post(f"/api/assets/{asset.id}/undelete")).status_code == 404

    await login_as(client, owner)
    mcp = (await client.get("/api/assets/trash", params={"project_id": str(project.id)})).json()
    assert [i["slug"] for i in mcp["items"]] == [asset.slug]
    assert mcp["items"][0]["deleted_by"]["id"] == str(author.id)
    r = await client.post(f"/api/assets/{asset.id}/undelete")
    assert r.status_code == 200 and r.json()["noop"] is False
    await session.refresh(asset)
    assert asset.deleted_at is None and asset.purge_at is None and asset.deleted_by is None


@pytest.mark.asyncio
async def test_restore_needs_room_in_the_owners_quota(client, session):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    asset.size_bytes = 2048
    asset.deleted_at = datetime.now(UTC)
    user.storage_quota_bytes = 1024
    await session.commit()
    await login_as(client, user)

    r = await client.post(f"/api/assets/{asset.id}/undelete")
    assert r.status_code == 413
    assert r.json()["code"] == "storage_quota_exceeded"
    await session.refresh(asset)
    assert asset.deleted_at is not None


@pytest.mark.asyncio
async def test_purge_removes_the_row_and_its_files(client, session, fs_storage):
    user = await mk_user(session)
    asset = await mk_asset(session, user)
    await session.commit()
    await put_blob(asset, "doc.md", b"# gone")
    await login_as(client, user)

    # Only from the trash.
    assert (await client.post(f"/api/assets/{asset.id}/purge")).status_code == 404
    await client.delete(f"/api/assets/{asset.id}")
    r = await client.post(f"/api/assets/{asset.id}/purge")
    assert r.status_code == 200 and r.json()["purged"] is True

    asset_id = asset.id
    session.expunge_all()
    assert await session.get(Asset, asset_id) is None
    storage = storage_from_url(get_settings().storage_url)
    assert not await storage.exists(f"{asset.storage_prefix}/v1/doc.md")
    purged = await session.scalar(
        select(AuditLog).where(
            AuditLog.target == f"asset:{asset_id}", AuditLog.action == "asset_purged"
        )
    )
    assert purged is not None


@pytest.mark.asyncio
async def test_empty_trash_of_one_project(client, session, fs_storage):
    user = await mk_user(session)
    project = await _project(session, user)
    in_project = await mk_asset(session, user)
    in_project.project_id = project.id
    elsewhere = await mk_asset(session, user)
    for a in (in_project, elsewhere):
        a.deleted_at = datetime.now(UTC)
    await session.commit()
    await login_as(client, user)

    r = await client.post("/api/assets/trash/purge", json={"project_id": str(project.id)})
    assert r.json() == {"purged": 1, "remaining": 0}
    session.expunge_all()
    assert await session.get(Asset, in_project.id) is None
    assert await session.get(Asset, elsewhere.id) is not None


@pytest.mark.asyncio
async def test_purge_expired_takes_only_what_is_due(session, fs_storage):
    user = await mk_user(session)
    due = await mk_asset(session, user)
    waiting = await mk_asset(session, user)
    now = datetime.now(UTC)
    due.deleted_at, due.purge_at = now - timedelta(days=31), now - timedelta(minutes=1)
    waiting.deleted_at, waiting.purge_at = now, now + timedelta(days=30)
    await session.commit()

    purged = await asset_lifecycle.purge_expired(session, get_settings())
    await session.commit()
    assert purged >= 1
    session.expunge_all()
    assert await session.get(Asset, due.id) is None
    assert await session.get(Asset, waiting.id) is not None


@pytest.mark.asyncio
async def test_trash_route_is_not_taken_for_an_asset_id(client, session):
    user = await mk_user(session)
    await session.commit()
    await login_as(client, user)
    r = await client.get("/api/assets/trash")
    assert r.status_code == 200
    assert r.json() == {"items": [], "total": 0, "next_offset": None}


@pytest.mark.asyncio
async def test_admin_sees_and_empties_the_organisation_trash_only_on_request(
    client, session, fs_storage
):
    admin = await mk_admin(session)
    other = await mk_user(session)
    mine = await mk_asset(session, admin)
    theirs = await mk_asset(session, other)
    for a in (mine, theirs):
        a.deleted_at = datetime.now(UTC)
    await session.commit()
    await login_as(client, admin)

    own = await _slugs(client, ("scope", "state:trash"))
    assert mine.slug in own and theirs.slug not in own
    everyone = await _slugs(client, ("scope", "admin:trash"))
    assert {mine.slug, theirs.slug} <= everyone

    # Emptying the own trash leaves other people's documents alone.
    r = await client.post("/api/assets/trash/purge", json={})
    assert r.status_code == 200
    session.expunge_all()
    assert await session.get(Asset, mine.id) is None
    assert await session.get(Asset, theirs.id) is not None

    r = await client.post("/api/assets/trash/purge", json={"everyone": True})
    assert r.status_code == 200
    session.expunge_all()
    assert await session.get(Asset, theirs.id) is None


@pytest.mark.asyncio
async def test_the_organisation_trash_is_the_own_trash_for_a_non_admin(client, session, fs_storage):
    user = await mk_user(session)
    other = await mk_user(session)
    mine = await mk_asset(session, user)
    theirs = await mk_asset(session, other)
    for a in (mine, theirs):
        a.deleted_at = datetime.now(UTC)
    await session.commit()
    await login_as(client, user)

    assert await _slugs(client, ("scope", "admin:trash")) == {mine.slug}
    await client.post("/api/assets/trash/purge", json={"everyone": True})
    session.expunge_all()
    assert await session.get(Asset, theirs.id) is not None
