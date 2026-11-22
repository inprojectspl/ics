"""Files of rows removed for good: the purge against a restore, retries after
a storage failure, and an account deletion (`services.storage_cleanup`)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import get_settings
from app.domain_errors import NotFoundError
from app.models import Asset, MicroAppPlan, StorageCleanup, User
from app.routes.admin_users import delete_user
from app.services import asset_lifecycle, storage_cleanup
from app.slug import generate_token
from app.storage import FSStorage, storage_from_url
from tests.conftest import mk_admin, mk_asset, mk_user, put_blob

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("fs_storage")]


async def _one(data: bytes):
    yield data


def _storage():
    return storage_from_url(get_settings().storage_url)


async def _trashed(session, owner: User) -> Asset:
    asset = await mk_asset(session, owner)
    asset.deleted_at = asset.purge_at = datetime.now(UTC)
    await session.commit()
    await put_blob(asset, "doc.md", b"# kept or gone")
    return asset


async def _pending(session) -> list[StorageCleanup]:
    return list((await session.scalars(select(StorageCleanup))).all())


async def test_a_restore_committed_after_the_read_beats_the_purge(session):
    owner = await mk_user(session)
    asset = await _trashed(session, owner)

    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as other:
        restoring = await other.get(Asset, asset.id)
        await asset_lifecycle.restore(other, await other.get(User, owner.id), restoring)
        await other.commit()

    assert await asset_lifecycle.purge(session, get_settings(), [asset.id], actor="test") == 0
    session.expunge_all()
    kept = await session.get(Asset, asset.id)
    assert kept is not None and kept.deleted_at is None
    assert await _storage().exists(f"{asset.storage_prefix}/v1/doc.md")
    assert await _pending(session) == []


async def test_a_restore_after_the_purge_finds_nothing(session):
    owner = await mk_user(session)
    asset = await _trashed(session, owner)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as other:
        stale = await other.get(Asset, asset.id)
        stale_owner = await other.get(User, owner.id)
        await other.commit()
        assert await asset_lifecycle.purge(session, get_settings(), [asset.id], actor="test") == 1
        with pytest.raises(NotFoundError):
            await asset_lifecycle.restore(other, stale_owner, stale)


async def test_files_a_storage_error_kept_are_deleted_by_a_later_run(session, monkeypatch):
    owner = await mk_user(session)
    asset = await _trashed(session, owner)
    real = FSStorage.delete_prefix

    async def broken(self, prefix):
        raise OSError("storage down")

    monkeypatch.setattr(FSStorage, "delete_prefix", broken)
    purged = await asset_lifecycle.purge(session, get_settings(), [asset.id], actor="test")
    assert purged == 1
    session.expunge_all()
    assert await session.get(Asset, asset.id) is None
    [left] = await _pending(session)
    assert left.prefix == f"{asset.storage_prefix}/"
    assert left.attempts == 1 and "storage down" in (left.last_error or "")
    assert await _storage().exists(f"{asset.storage_prefix}/v1/doc.md")

    monkeypatch.setattr(FSStorage, "delete_prefix", real)
    assert await storage_cleanup.sweep(session, get_settings()) == 1
    assert await _pending(session) == []
    assert not await _storage().exists(f"{asset.storage_prefix}/v1/doc.md")


async def test_deleting_an_account_deletes_the_files_of_its_assets(session):
    admin = await mk_admin(session)
    victim = await mk_user(session)
    active = await mk_asset(session, victim)
    trashed = await mk_asset(session, victim)
    trashed.deleted_at = datetime.now(UTC)
    other = await mk_asset(session, admin)
    await session.commit()
    for asset in (active, trashed, other):
        await put_blob(asset, "doc.md", b"x")

    out = await delete_user(victim.id, admin, session, get_settings())
    assert out == {"deleted": True, "cascade_assets": 2}
    storage = _storage()
    assert not await storage.exists(f"{active.storage_prefix}/v1/doc.md")
    assert not await storage.exists(f"{trashed.storage_prefix}/v1/doc.md")
    assert await storage.exists(f"{other.storage_prefix}/v1/doc.md")
    assert await _pending(session) == []


async def test_deleting_an_account_deletes_the_files_of_its_new_app_plans(session):
    # A plan for a new app has no asset; the cascade from the user removes it.
    admin = await mk_admin(session)
    victim = await mk_user(session)
    prefix = f"microapp-plans/{generate_token()}"
    session.add(
        MicroAppPlan(
            id=generate_token()[:40],
            user_id=victim.id,
            action="create",
            digest="sha256:x",
            storage_prefix=prefix,
            files=[],
            manifest={},
            contract_version="1",
            expected_generation=0,
            migration={},
            expires_at=datetime.now(UTC),
        )
    )
    await session.commit()
    storage = _storage()
    await storage.put(f"{prefix}/app.json", _one(b"{}"))

    await delete_user(victim.id, admin, session, get_settings())
    assert not await storage.exists(f"{prefix}/app.json")
