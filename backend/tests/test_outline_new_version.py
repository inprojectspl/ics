"""A new asset version makes the cached outline stale and gets it rebuilt.

Otherwise the sweeper skips the row and `GET outline` keeps serving the
previous version's outline to agents.
"""

from __future__ import annotations

import pathlib
import tempfile
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.jobs.tasks import outline as outline_mod
from app.models import Asset
from tests.conftest import mk_md_single


@pytest.fixture
def outline_env(monkeypatch, session):
    tmp = tempfile.mkdtemp(prefix="outline-nv-")
    monkeypatch.setattr(get_settings(), "storage_url", f"fs://{tmp}")
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(outline_mod, "SessionLocal", factory)
    yield pathlib.Path(tmp)


@pytest.fixture
def pool(monkeypatch):
    """Capture jobs enqueued by the sweeper and by the route."""
    pool = AsyncMock()

    async def _get_pool():
        return pool

    monkeypatch.setattr("app.jobs.queue.get_pool", _get_pool)
    return pool


async def _fresh_asset(client, session) -> Asset:
    _, asset = await mk_md_single(client, session, content="# Old title\n\nbody\n", entry="doc.md")
    await outline_mod.rebuild_outline({}, str(asset.id))
    await session.refresh(asset)
    assert asset.outline_status == "fresh"
    assert asset.outline_version == 1
    return asset


async def _new_version(client, asset: Asset) -> None:
    r = await client.put(
        f"/api/assets/{asset.id}/content", json={"content": "# New title\n\nbody\n"}
    )
    assert r.status_code == 201, r.text


@pytest.mark.asyncio
async def test_sweeper_rebuilds_after_new_version(outline_env, pool, client, session):
    asset = await _fresh_asset(client, session)

    await _new_version(client, asset)
    await session.refresh(asset)
    assert asset.version == 2
    assert asset.outline_status == "stale"

    result = await outline_mod.outline_stale_sweeper({})

    assert str(asset.id) in result["recovered"]
    queued = [c.args for c in pool.enqueue_job.await_args_list]
    assert ("rebuild_outline", str(asset.id)) in queued


@pytest.mark.asyncio
async def test_sweeper_skips_outline_built_for_current_version(outline_env, pool, client, session):
    asset = await _fresh_asset(client, session)

    result = await outline_mod.outline_stale_sweeper({})

    assert str(asset.id) not in result["recovered"]


@pytest.mark.asyncio
async def test_sweeper_catches_version_committed_during_build(
    outline_env, pool, client, session, monkeypatch
):
    """The build reads v1; v2 lands before it writes: the result must stay stale."""
    _, asset = await mk_md_single(client, session, content="# Old title\n", entry="doc.md")
    real_build = outline_mod.build_outline_payload

    async def _build_then_bump(a, settings):
        payload = await real_build(a, settings)
        await _new_version(client, asset)
        return payload

    monkeypatch.setattr(outline_mod, "build_outline_payload", _build_then_bump)
    await outline_mod.rebuild_outline({}, str(asset.id))

    await session.refresh(asset)
    assert asset.version == 2
    assert asset.outline_version == 1
    assert asset.outline_status == "stale"
    result = await outline_mod.outline_stale_sweeper({})
    assert str(asset.id) in result["recovered"]


@pytest.mark.asyncio
async def test_endpoint_serves_current_outline_after_rebuild(
    outline_env, pool, client, session, monkeypatch
):
    route_enqueue = AsyncMock()
    monkeypatch.setattr("app.routes.mcp_assets.outline.enqueue", route_enqueue)
    asset = await _fresh_asset(client, session)
    asset_id, slug = str(asset.id), asset.slug
    await _new_version(client, asset)

    stale = await client.get(f"/api/assets/by-slug/{slug}/outline")
    assert stale.status_code == 200
    assert stale.headers.get("X-Outline-Stale") == "true"
    route_enqueue.assert_awaited_with("rebuild_outline", asset_id, _job_id=f"outline:{asset_id}")

    await outline_mod.rebuild_outline({}, asset_id)
    # The worker wrote through its own session; each production request has
    # a fresh one, the test shares a session, so drop its cached row.
    session.expire_all()
    fresh = await client.get(f"/api/assets/by-slug/{slug}/outline")

    assert fresh.status_code == 200
    assert "X-Outline-Stale" not in fresh.headers
    assert "New title" in str(fresh.json())
    assert "Old title" not in str(fresh.json())
