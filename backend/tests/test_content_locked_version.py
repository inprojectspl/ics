"""Concurrent requests must validate and account against the locked version."""

import asyncio
from contextlib import asynccontextmanager
from io import BytesIO

import pytest
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.collections_io import list_version_files, read_bytes_at_version
from app.config import get_settings
from app.errors import ApiError
from app.models import AssetVersion, AuditLog, User
from app.quota import QuotaExceededError
from app.routes.assets import content
from app.routes.assets.file_move import MoveFileIn, move_file_in_collection
from app.services import asset_versions
from app.storage import FSStorage
from tests.conftest import mk_asset, mk_user, put_blob

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("fs_storage")]


async def vault(session, files, *, kind="md_collection"):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind=kind, entry_path="index.md")
    for path, data in files.items():
        await put_blob(asset, path, data)
    asset.size_bytes = sum(map(len, files.values()))
    await session.commit()
    return owner, asset


async def edit(session, owner, asset_id, text, path="index.md"):
    return await content.edit_content(
        asset_id, content.EditContentIn(content=text, path=path), owner, session, get_settings()
    )


async def add(session, owner, asset_id, text, path="new.md"):
    return await content.add_file_to_collection(
        asset_id,
        UploadFile(BytesIO(text.encode()), filename=path),
        owner,
        session,
        get_settings(),
        path=path,
    )


async def remove(session, owner, asset_id, path):
    return await content.delete_file_in_collection(
        asset_id, owner, session, get_settings(), path=path
    )


@asynccontextmanager
async def paused_request(session, owner, monkeypatch, operation):
    """Pause one request after it has built its intent, before taking the row lock."""
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as delayed:
        delayed_owner = await delayed.get(User, owner.id)
        reached, release = asyncio.Event(), asyncio.Event()
        original = asset_versions.commit_new_version

        async def barrier(current, *args, **kwargs):
            if current is delayed:
                reached.set()
                await release.wait()
            return await original(current, *args, **kwargs)

        monkeypatch.setattr(asset_versions, "commit_new_version", barrier)
        task = asyncio.create_task(operation(delayed, delayed_owner))
        try:
            await asyncio.wait_for(reached.wait(), 5)
            yield task
        finally:
            release.set()
            if not task.done():
                # The caller observes the result after leaving this context.
                await asyncio.wait({task}, timeout=5)
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("kind", ["md_single", "md_collection"])
async def test_5_to_10_to_7_counts_locked_tree(session, monkeypatch, kind):
    owner, asset = await vault(session, {"index.md": b"12345"}, kind=kind)
    async with paused_request(
        session, owner, monkeypatch, lambda s, u: edit(s, u, asset.id, "1234567")
    ) as task:
        await edit(session, owner, asset.id, "1234567890")
    result = await task
    assert result["version"] == 3
    assert result["size_bytes"] == 7
    await session.refresh(asset)
    assert asset.size_bytes == 7
    rows = (
        (
            await session.execute(
                select(AssetVersion)
                .where(AssetVersion.asset_id == asset.id)
                .order_by(AssetVersion.version)
            )
        )
        .scalars()
        .all()
    )
    assert [(row.version, row.size_bytes) for row in rows] == [(2, 10), (3, 7)]
    assert await read_bytes_at_version(asset, 1, "index.md", get_settings()) == b"12345"
    assert await read_bytes_at_version(asset, 2, "index.md", get_settings()) == b"1234567890"
    audits = (
        (await session.execute(select(AuditLog).where(AuditLog.target == f"asset:{asset.id}")))
        .scalars()
        .all()
    )
    assert next(a.payload for a in audits if a.payload["version"] == 3)["old_bytes"] == 10


@pytest.mark.parametrize("empty", [False, True])
async def test_delayed_add_cannot_overwrite_concurrent_add(session, monkeypatch, empty):
    owner, asset = await vault(session, {"index.md": b"keep"})

    async def delayed(s, u):
        if empty:
            return await content.create_empty_file_in_collection(
                asset.id, content.NewEmptyFileIn(path="new.md"), u, s, get_settings()
            )
        return await add(s, u, asset.id, "second")

    async with paused_request(session, owner, monkeypatch, delayed) as task:
        await add(session, owner, asset.id, "first")
    with pytest.raises(ApiError) as exc:
        await task
    assert (exc.value.status_code, exc.value.code) == (409, "file_exists")
    await session.refresh(asset)
    assert asset.version == 2
    assert asset.size_bytes == 9
    assert await list_version_files(asset, 3, get_settings()) == []
    assert await read_bytes_at_version(asset, 2, "new.md", get_settings()) == b"first"


@pytest.mark.parametrize("operation", ["edit", "delete"])
async def test_delayed_operation_rejects_file_deleted_by_other_writer(
    session, monkeypatch, operation
):
    owner, asset = await vault(session, {"index.md": b"keep", "gone.md": b"old"})

    async def delayed(s, u):
        if operation == "edit":
            return await edit(s, u, asset.id, "resurrected", "gone.md")
        return await remove(s, u, asset.id, "gone.md")

    async with paused_request(session, owner, monkeypatch, delayed) as task:
        await remove(session, owner, asset.id, "gone.md")
    with pytest.raises(ApiError) as exc:
        await task
    assert (exc.value.status_code, exc.value.code) == (404, "file_not_found")
    await session.refresh(asset)
    assert (asset.version, asset.size_bytes) == (2, 4)
    assert await list_version_files(asset, 3, get_settings()) == []


async def test_delayed_delete_rechecks_last_file(session, monkeypatch):
    owner, asset = await vault(session, {"index.md": b"i", "other.md": b"o"})
    async with paused_request(
        session, owner, monkeypatch, lambda s, u: remove(s, u, asset.id, "index.md")
    ) as task:
        await remove(session, owner, asset.id, "other.md")
    with pytest.raises(ApiError) as exc:
        await task
    assert (exc.value.status_code, exc.value.code) == (400, "last_file")
    await session.refresh(asset)
    assert (asset.version, asset.entry_path, asset.size_bytes) == (2, "index.md", 1)


async def test_delayed_edit_rechecks_no_changes(session, monkeypatch):
    owner, asset = await vault(session, {"index.md": b"old"})
    async with paused_request(
        session, owner, monkeypatch, lambda s, u: edit(s, u, asset.id, "same")
    ) as task:
        await edit(session, owner, asset.id, "same")
    with pytest.raises(ApiError) as exc:
        await task
    assert (exc.value.status_code, exc.value.code) == (400, "no_changes")
    await session.refresh(asset)
    assert asset.version == 2


async def test_concurrent_shrink_does_not_consume_false_growth_quota(session, monkeypatch):
    owner, asset = await vault(session, {"index.md": b"12345"})
    owner.storage_quota_bytes = 10
    await session.commit()
    async with paused_request(
        session, owner, monkeypatch, lambda s, u: edit(s, u, asset.id, "1234567")
    ) as task:
        await edit(session, owner, asset.id, "1234567890")
    assert (await task)["size_bytes"] == 7


async def move(session, owner, asset_id, source="index.md", target="moved.md"):
    return await move_file_in_collection(
        asset_id, MoveFileIn(from_path=source, to_path=target), owner, session, get_settings()
    )


async def test_delayed_move_uses_locked_source_content(session, monkeypatch):
    owner, asset = await vault(session, {"index.md": b"12345"})
    async with paused_request(
        session, owner, monkeypatch, lambda s, u: move(s, u, asset.id)
    ) as task:
        await edit(session, owner, asset.id, "1234567890")
    assert (await task)["entry_path"] == "moved.md"
    await session.refresh(asset)
    assert (asset.version, asset.size_bytes) == (3, 10)
    assert await read_bytes_at_version(asset, 3, "moved.md", get_settings()) == b"1234567890"


async def test_delayed_move_cannot_overwrite_concurrent_destination(session, monkeypatch):
    owner, asset = await vault(session, {"index.md": b"keep"})
    async with paused_request(
        session, owner, monkeypatch, lambda s, u: move(s, u, asset.id)
    ) as task:
        await add(session, owner, asset.id, "first", "moved.md")
    with pytest.raises(ApiError) as exc:
        await task
    assert (exc.value.status_code, exc.value.code) == (409, "file_exists")
    await session.refresh(asset)
    assert (asset.version, asset.entry_path, asset.size_bytes) == (2, "index.md", 9)


async def test_delete_keeps_case_insensitive_markdown_paths(session):
    owner, asset = await vault(session, {"index.md": b"keep", "UPPER.MD": b"remove"})
    result = await remove(session, owner, asset.id, "UPPER.MD")
    assert (result["version"], result["size_bytes"]) == (2, 4)


async def test_concurrent_growth_cannot_bypass_quota_using_stale_delta(session, monkeypatch):
    owner, asset = await vault(session, {"index.md": b"1234567890"})
    owner.storage_quota_bytes = 6
    await session.commit()
    async with paused_request(
        session, owner, monkeypatch, lambda s, u: edit(s, u, asset.id, "1234567")
    ) as task:
        await edit(session, owner, asset.id, "12345")
    with pytest.raises(QuotaExceededError):
        await task
    await session.refresh(asset)
    assert (asset.version, asset.size_bytes) == (2, 5)
    assert await list_version_files(asset, 3, get_settings()) == []
    assert await read_bytes_at_version(asset, 2, "index.md", get_settings()) == b"12345"


async def test_storage_measurement_failure_discards_only_new_tree(session, monkeypatch):
    owner, asset = await vault(session, {"index.md": b"keep"})
    original = FSStorage.list_prefix_stats

    async def failed_measurement(storage, prefix):
        if prefix == f"{asset.storage_prefix}/v2/":
            raise OSError("synthetic storage stat failure")
        return await original(storage, prefix)

    with monkeypatch.context() as patch:
        patch.setattr(FSStorage, "list_prefix_stats", failed_measurement)
        with pytest.raises(OSError, match="synthetic storage stat failure"):
            await edit(session, owner, asset.id, "new content")
        await session.rollback()
    await session.refresh(asset)
    assert (asset.version, asset.size_bytes) == (1, 4)
    assert await list_version_files(asset, 2, get_settings()) == []
    assert await read_bytes_at_version(asset, 1, "index.md", get_settings()) == b"keep"
    assert (
        not (await session.execute(select(AssetVersion).where(AssetVersion.asset_id == asset.id)))
        .scalars()
        .all()
    )
