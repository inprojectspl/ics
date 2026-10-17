"""Sort order of the home list (`GET /api/assets`) and search (`/api/assets/search`)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Asset, AssetPin, User
from app.slug import generate_slug
from tests.conftest import login_as, mk_user, put_blob

BASE = datetime(2026, 1, 1, tzinfo=UTC)


async def _asset(
    session,
    owner: User,
    *,
    title: str,
    version: int = 1,
    created: int = 0,
    updated: int = 0,
) -> Asset:
    asset = Asset(
        slug=generate_slug(),
        owner_id=owner.id,
        kind="md_single",
        title=title,
        storage_prefix=generate_slug(8),
        entry_path="doc.md",
        security_status="clean",
        version=version,
        search_content=f"needle {title}",
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
    # Created first, changed last: a creation-ordered list would sink this
    # busy document to the bottom.
    busy = await _asset(session, owner, title="busy", version=61, created=0, updated=9)
    fresh = await _asset(session, owner, title="fresh", version=1, created=5, updated=5)
    idle = await _asset(session, owner, title="idle", version=2, created=3, updated=3)
    await session.commit()
    await login_as(client, owner)
    return owner, {"busy": busy, "fresh": fresh, "idle": idle}


async def _list(client, **params) -> list[str]:
    r = await client.get("/api/assets", params=params)
    assert r.status_code == 200
    return [a["title"] for a in r.json()["items"]]


async def _search(client, **params) -> list[str]:
    r = await client.get("/api/assets/search", params={"q": "needle", **params})
    assert r.status_code == 200
    return [a["title"] for a in r.json()]


@pytest.mark.asyncio
async def test_list_defaults_to_last_change_first(client, seeded):
    assert await _list(client) == ["busy", "fresh", "idle"]


@pytest.mark.asyncio
async def test_list_accepts_sort_and_order(client, seeded):
    assert await _list(client, sort="created") == ["fresh", "idle", "busy"]
    assert await _list(client, sort="updated", order="asc") == ["idle", "fresh", "busy"]
    assert await _list(client, sort="versions") == ["busy", "idle", "fresh"]
    assert await _list(client, sort="title", order="desc") == ["idle", "fresh", "busy"]


@pytest.mark.asyncio
async def test_list_pages_follow_the_sort(client, seeded):
    first = await _list(client, sort="created", page=1, page_size=2)
    second = await _list(client, sort="created", page=2, page_size=2)
    assert first + second == ["fresh", "idle", "busy"]


@pytest.mark.asyncio
async def test_pins_do_not_reorder_the_list(session, client, seeded):
    owner, assets = seeded
    for name in ("idle", "fresh"):
        session.add(AssetPin(user_id=owner.id, asset_id=assets[name].id))
    await session.commit()
    assert await _list(client) == ["busy", "fresh", "idle"]


@pytest.mark.asyncio
async def test_search_uses_the_same_order(client, seeded):
    assert await _search(client) == ["busy", "fresh", "idle"]
    assert await _search(client, sort="title") == ["busy", "fresh", "idle"]
    assert await _search(client, sort="created") == ["fresh", "idle", "busy"]
    rows = (await client.get("/api/assets/search", params={"q": "needle"})).json()
    assert rows[0]["updated_at"] == (BASE + timedelta(days=9)).isoformat()


@pytest.mark.asyncio
async def test_rejects_an_unknown_sort_key(client, seeded):
    assert (await client.get("/api/assets", params={"sort": "size"})).status_code == 422
    assert (await client.get("/api/assets", params={"order": "up"})).status_code == 422


@pytest.mark.asyncio
async def test_a_content_change_moves_the_asset_to_the_top(client, seeded, fs_storage):
    _, assets = seeded
    idle = assets["idle"]
    await put_blob(idle, "doc.md", b"# Idle\n")
    r = await client.put(f"/api/assets/{idle.id}/content", json={"content": "# Idle\n\nedited"})
    assert r.status_code == 201, r.text
    assert (await _list(client))[0] == "idle"
