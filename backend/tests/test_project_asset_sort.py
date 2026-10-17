"""Sort order of the project file list (`GET /api/projects/{slug}`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.models import Asset, AssetPin, Project, ProjectMember, User
from app.slug import generate_slug
from tests.conftest import login_as, mk_user

BASE = datetime(2026, 1, 1, tzinfo=UTC)


async def _project(session, owner: User) -> Project:
    project = Project(slug=generate_slug(), name="Sort", created_by=owner.id)
    session.add(project)
    await session.flush()
    session.add(
        ProjectMember(
            project_id=project.id,
            user_id=owner.id,
            role="owner",
            accepted_at=BASE,
        )
    )
    await session.flush()
    return project


async def _asset(
    session,
    owner: User,
    project: Project,
    *,
    title: str,
    kind: str = "md_single",
    version: int = 1,
    created: int = 0,
    updated: int = 0,
) -> Asset:
    asset = Asset(
        slug=generate_slug(),
        owner_id=owner.id,
        project_id=project.id,
        kind=kind,
        title=title,
        storage_prefix=generate_slug(8),
        entry_path="doc.md",
        security_status="clean",
        version=version,
        created_at=BASE + timedelta(days=created),
        updated_at=BASE + timedelta(days=updated),
        # The list sorts by content change; these rows changed content when touched.
        content_updated_at=BASE + timedelta(days=updated),
    )
    session.add(asset)
    await session.flush()
    return asset


@pytest.fixture
async def seeded(session, client):
    owner = await mk_user(session)
    project = await _project(session, owner)
    # `alpha` is the oldest by creation but the most recently changed one.
    await _asset(session, owner, project, title="alpha", version=3, created=0, updated=9)
    await _asset(
        session, owner, project, title="Bravo", kind="html_bundle", version=61, created=1, updated=2
    )
    await _asset(
        session,
        owner,
        project,
        title="charlie",
        kind="md_collection",
        version=1,
        created=2,
        updated=5,
    )
    await session.commit()
    await login_as(client, owner)
    return owner, project


async def _titles(client, slug: str, **params) -> list[str]:
    r = await client.get(f"/api/projects/{slug}", params=params)
    assert r.status_code == 200
    return [a["title"] for a in r.json()["assets"]]


@pytest.mark.asyncio
async def test_default_is_last_updated_first(client, seeded):
    _, project = seeded
    assert await _titles(client, project.slug) == ["alpha", "charlie", "Bravo"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"sort": "updated", "order": "asc"}, ["Bravo", "charlie", "alpha"]),
        ({"sort": "created"}, ["charlie", "Bravo", "alpha"]),
        ({"sort": "created", "order": "asc"}, ["alpha", "Bravo", "charlie"]),
        # Case-insensitive A-Z by default.
        ({"sort": "title"}, ["alpha", "Bravo", "charlie"]),
        ({"sort": "title", "order": "desc"}, ["charlie", "Bravo", "alpha"]),
        ({"sort": "versions"}, ["Bravo", "alpha", "charlie"]),
        ({"sort": "kind"}, ["Bravo", "charlie", "alpha"]),
    ],
)
async def test_sort_keys(client, seeded, params, expected):
    _, project = seeded
    assert await _titles(client, project.slug, **params) == expected


@pytest.mark.asyncio
async def test_pins_do_not_reorder_the_project_list(session, client, seeded):
    owner, project = seeded
    rows = (await client.get(f"/api/projects/{project.slug}")).json()["assets"]
    by_title = {a["title"]: a["id"] for a in rows}
    for title in ("Bravo", "charlie"):
        session.add(AssetPin(user_id=owner.id, asset_id=UUID(by_title[title])))
    await session.commit()

    assert await _titles(client, project.slug, sort="title") == ["alpha", "Bravo", "charlie"]


@pytest.mark.asyncio
async def test_rows_carry_updated_at(client, seeded):
    _, project = seeded
    rows = (await client.get(f"/api/projects/{project.slug}")).json()["assets"]
    assert rows[0]["updated_at"] == (BASE + timedelta(days=9)).isoformat()


@pytest.mark.asyncio
async def test_unknown_sort_key_is_rejected(client, seeded):
    _, project = seeded
    r = await client.get(f"/api/projects/{project.slug}", params={"sort": "size"})
    assert r.status_code == 422
