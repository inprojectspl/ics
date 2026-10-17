"""Worker `jobs/tasks/outline.py`: `rebuild_outline` and `outline_stale_sweeper`.

The module-level `SessionLocal` in outline.py uses `app.db.engine`, which we
do not want in tests (event-loop drift between pytest-asyncio tests). We
patch SessionLocal with a sessionmaker built from `session.bind` (conftest
fixture), so the whole worker writes to the same connection as the test code.
"""

from __future__ import annotations

import pathlib
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.jobs.tasks import outline as outline_mod
from app.models import Asset
from app.slug import generate_slug
from tests.conftest import mk_user


@pytest.fixture
def outline_env(monkeypatch, session):
    """Wire the outline worker to the fixture session + temp fs storage.

    Cleanup is automatic: monkeypatch restores the module-level SessionLocal
    and tempfile removes the directory.
    """
    tmp = tempfile.mkdtemp(prefix="outline-test-")
    monkeypatch.setattr(get_settings(), "storage_url", f"fs://{tmp}")
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    monkeypatch.setattr(outline_mod, "SessionLocal", factory)
    yield pathlib.Path(tmp)


def _write_under(root: pathlib.Path, rel_path: str, content: str) -> None:
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------- rebuild_outline: kinds ----------


@pytest.mark.asyncio
async def test_rebuild_outline_md_single(outline_env, session):
    user = await mk_user(session)
    slug = generate_slug()
    prefix = f"assets/{slug}"
    asset = Asset(
        slug=slug,
        owner_id=user.id,
        kind="md_single",
        title="Single Doc",
        storage_prefix=prefix,
        entry_path="doc.md",
        security_status="clean",
        size_bytes=100,
        version=1,
        outline_status="stale",
    )
    session.add(asset)
    await session.commit()

    md_content = "# Heading 1\n\nIntro paragraph.\n\n## Heading 2\n\nMore."
    _write_under(outline_env, f"{prefix}/v1/doc.md", md_content)

    result = await outline_mod.rebuild_outline({}, str(asset.id))
    assert result["asset_id"] == str(asset.id)
    assert result.get("outline_version") == 1

    await session.refresh(asset)
    assert asset.outline_status == "fresh"
    assert asset.outline_version == 1
    assert asset.outline_built_at is not None
    assert asset.outline_error is None
    assert asset.outline_json is not None


@pytest.mark.asyncio
async def test_rebuild_outline_md_collection(outline_env, session):
    user = await mk_user(session)
    slug = generate_slug()
    prefix = f"assets/{slug}"
    asset = Asset(
        slug=slug,
        owner_id=user.id,
        kind="md_collection",
        title="Vault",
        storage_prefix=prefix,
        entry_path="index.md",
        security_status="clean",
        size_bytes=200,
        version=1,
        outline_status="stale",
    )
    session.add(asset)
    await session.commit()

    _write_under(outline_env, f"{prefix}/v1/index.md", "# Index\n\nWelcome.")
    _write_under(outline_env, f"{prefix}/v1/notes/page.md", "# Page\n\n[[index]]")
    _write_under(outline_env, f"{prefix}/v1/notes/other.md", "## H2\n\nNo wikilink.")

    await outline_mod.rebuild_outline({}, str(asset.id))
    await session.refresh(asset)

    assert asset.outline_status == "fresh"
    assert asset.outline_json is not None


@pytest.mark.asyncio
async def test_rebuild_outline_html_bundle(outline_env, session):
    user = await mk_user(session)
    slug = generate_slug()
    prefix = f"assets/{slug}"
    asset = Asset(
        slug=slug,
        owner_id=user.id,
        kind="html_bundle",
        title="Demo",
        storage_prefix=prefix,
        entry_path="index.html",
        security_status="clean",
        size_bytes=500,
        version=1,
        outline_status="stale",
    )
    session.add(asset)
    await session.commit()

    _write_under(outline_env, f"{prefix}/v1/index.html", "<html><body>Hi</body></html>")
    _write_under(outline_env, f"{prefix}/v1/style.css", "body{color:#000}")

    await outline_mod.rebuild_outline({}, str(asset.id))
    await session.refresh(asset)

    assert asset.outline_status == "fresh"
    assert asset.outline_json is not None


# ---------- rebuild_outline: graceful no-ops ----------


@pytest.mark.asyncio
async def test_rebuild_outline_missing_asset_skip(outline_env, session):
    """Asset id pointing at a missing row -> graceful skip, no raise."""
    fake_uuid = "00000000-0000-0000-0000-000000000999"
    result = await outline_mod.rebuild_outline({}, fake_uuid)
    assert result.get("skipped") == "deleted_or_missing"


@pytest.mark.asyncio
async def test_rebuild_outline_deleted_asset_skip(outline_env, session):
    user = await mk_user(session)
    slug = generate_slug()
    asset = Asset(
        slug=slug,
        owner_id=user.id,
        kind="md_single",
        title="Dead",
        storage_prefix=f"assets/{slug}",
        entry_path="doc.md",
        security_status="clean",
        size_bytes=0,
        version=1,
        deleted_at=datetime.now(UTC),
    )
    session.add(asset)
    await session.commit()

    result = await outline_mod.rebuild_outline({}, str(asset.id))
    assert result.get("skipped") == "deleted_or_missing"


@pytest.mark.asyncio
async def test_rebuild_outline_failure_records_error(outline_env, session):
    """Missing storage file -> asset.outline_status flips to `failed`.

    The worker catches the exception from `read_all` (FileNotFoundError)
    and stores `outline_error` instead of crashing.
    """
    user = await mk_user(session)
    slug = generate_slug()
    asset = Asset(
        slug=slug,
        owner_id=user.id,
        kind="md_single",
        title="Broken",
        storage_prefix=f"assets/{slug}",
        entry_path="missing.md",
        security_status="clean",
        size_bytes=0,
        version=1,
        outline_status="stale",
    )
    session.add(asset)
    await session.commit()
    # No file on FS: the worker gets FileNotFoundError from storage.get.

    result = await outline_mod.rebuild_outline({}, str(asset.id))
    assert "error" in result

    await session.refresh(asset)
    assert asset.outline_status == "failed"
    assert asset.outline_error is not None


# ---------- outline_stale_sweeper ----------


@pytest.mark.asyncio
async def test_stale_sweeper_recovers_stuck_building(outline_env, session, monkeypatch):
    """Building+old-updated_at -> flip to stale + enqueue rebuild."""
    user = await mk_user(session)
    stale_old = datetime.now(UTC) - timedelta(minutes=10)
    slug = generate_slug()
    asset = Asset(
        slug=slug,
        owner_id=user.id,
        kind="md_single",
        title="Stuck",
        storage_prefix=f"assets/{slug}",
        entry_path="doc.md",
        security_status="clean",
        size_bytes=0,
        version=1,
        outline_status="building",
        updated_at=stale_old,
    )
    session.add(asset)
    await session.commit()

    enqueue_mock = AsyncMock()
    pool_mock = AsyncMock()
    pool_mock.enqueue_job = enqueue_mock

    async def _fake_get_pool():
        return pool_mock

    monkeypatch.setattr("app.jobs.queue.get_pool", _fake_get_pool)

    result = await outline_mod.outline_stale_sweeper({})
    assert str(asset.id) in result["recovered"]
    assert result["count"] >= 1
    enqueue_mock.assert_called()

    await session.refresh(asset)
    assert asset.outline_status == "stale"


@pytest.mark.asyncio
async def test_stale_sweeper_picks_up_version_drift(outline_env, session, monkeypatch):
    """Asset bumped its version without an enqueue (outline_version < version) -> caught."""
    user = await mk_user(session)
    slug = generate_slug()
    asset = Asset(
        slug=slug,
        owner_id=user.id,
        kind="md_single",
        title="Drift",
        storage_prefix=f"assets/{slug}",
        entry_path="doc.md",
        security_status="clean",
        size_bytes=0,
        version=3,
        outline_status="stale",
        outline_version=1,
    )
    session.add(asset)
    await session.commit()

    enqueue_mock = AsyncMock()
    pool_mock = AsyncMock()
    pool_mock.enqueue_job = enqueue_mock

    async def _fake_get_pool():
        return pool_mock

    monkeypatch.setattr("app.jobs.queue.get_pool", _fake_get_pool)

    result = await outline_mod.outline_stale_sweeper({})
    assert str(asset.id) in result["recovered"]


@pytest.mark.asyncio
async def test_stale_sweeper_noop_when_all_fresh(outline_env, session, monkeypatch):
    """A fresh asset must not be picked up by the sweeper.

    We monkeypatch get_pool even though we expect it not to be called: the
    DB persists across tests, so stale assets from earlier tests may trigger
    the sweeper and call a real arq pool on a closed event loop ("Event loop
    is closed").
    """
    pool_mock = AsyncMock()
    pool_mock.enqueue_job = AsyncMock()

    async def _fake_get_pool():
        return pool_mock

    monkeypatch.setattr("app.jobs.queue.get_pool", _fake_get_pool)

    user = await mk_user(session)
    slug = generate_slug()
    asset = Asset(
        slug=slug,
        owner_id=user.id,
        kind="md_single",
        title="Fresh",
        storage_prefix=f"assets/{slug}",
        entry_path="doc.md",
        security_status="clean",
        size_bytes=0,
        version=1,
        outline_status="fresh",
        outline_version=1,
    )
    session.add(asset)
    await session.commit()

    result = await outline_mod.outline_stale_sweeper({})
    assert str(asset.id) not in result["recovered"]
