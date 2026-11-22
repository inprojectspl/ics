"""Checks that read many rows and then write: two concurrent writers must not
both pass on the state before the other's commit (the owner's quota, a
cycle of an acyclic relation type)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import quota
from app.config import get_settings
from app.domain_errors import ConflictError
from app.models import Asset, User
from app.services import asset_versions, relations
from tests.conftest import mk_asset, mk_user, put_blob

pytestmark = pytest.mark.asyncio


async def _wait_until_blocked(probe: AsyncSession, pid: int, task: asyncio.Task) -> None:
    async with asyncio.timeout(5):
        while not await probe.scalar(
            text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}
        ):
            if task.done():
                await task
                pytest.fail("the second writer finished without waiting")
            await asyncio.sleep(0.01)


async def test_two_growths_of_one_owner_cannot_both_pass_the_quota(session):
    owner = await mk_user(session)
    owner.storage_quota_bytes = 150
    a = await mk_asset(session, owner)
    b = await mk_asset(session, owner)
    a.size_bytes = b.size_bytes = 1
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as first, factory() as second:
        second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
        await quota.assert_can_grow(first, owner.id, incoming_bytes=100, quota_bytes=150)
        late = asyncio.create_task(
            quota.assert_can_grow(second, owner.id, incoming_bytes=100, quota_bytes=150)
        )
        await _wait_until_blocked(session, second_pid, late)
        (await first.get(Asset, a.id)).size_bytes = 101
        await first.commit()
        with pytest.raises(quota.QuotaExceededError):
            await late
        await second.rollback()


async def test_other_owners_do_not_wait_for_each_other(session):
    one, two = await mk_user(session), await mk_user(session)
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as first, factory() as second:
        await quota.assert_can_grow(first, one.id, incoming_bytes=1, quota_bytes=10**9)
        async with asyncio.timeout(5):
            await quota.assert_can_grow(second, two.id, incoming_bytes=1, quota_bytes=10**9)
        await first.rollback()
        await second.rollback()


async def test_opposite_part_of_edges_added_at_once_leave_no_cycle(session):
    owner = await mk_user(session)
    a = await mk_asset(session, owner)
    b = await mk_asset(session, owner)
    await session.commit()
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as first, factory() as second:
        second_pid = await second.scalar(text("SELECT pg_backend_pid()"))

        async def add(current: AsyncSession, source: Asset, target: Asset):
            return await relations.add_relation(
                current,
                actor=await current.get(User, owner.id),
                source_id=source.id,
                target_id=target.id,
                relation_type="part_of",
            )

        await add(first, a, b)
        late = asyncio.create_task(add(second, b, a))
        await _wait_until_blocked(session, second_pid, late)
        await first.commit()
        with pytest.raises(ConflictError) as exc:
            await late
        assert exc.value.code == "relation_cycle"
        await second.rollback()


async def test_a_version_write_locks_the_owner_only_for_its_commit(
    session, fs_storage, monkeypatch
):
    # The owner's row (quota) is locked only for the commit: a sign-in that
    # updates the user must not wait for scans, indexing or conversions.
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="index.md")
    await put_blob(asset, "index.md", b"a")
    asset.size_bytes = 1
    await session.commit()
    indexing, release = asyncio.Event(), asyncio.Event()
    extract = asset_versions.relation_extraction.extract_from_content

    async def slow_extract(*args, **kwargs):
        indexing.set()
        await release.wait()
        return await extract(*args, **kwargs)

    monkeypatch.setattr(asset_versions.relation_extraction, "extract_from_content", slow_extract)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    async with factory() as writer, factory() as signin:
        write = asyncio.create_task(
            asset_versions.commit_new_version(
                writer,
                await writer.get(Asset, asset.id),
                get_settings(),
                stage=asset_versions.edit_files(put={"index.md": b"grown"}),
                actor=await writer.get(User, owner.id),
                audit_action="test_versioned",
                audit_payload=lambda nv: {"version": nv.version},
            )
        )
        try:
            async with asyncio.timeout(5):
                await indexing.wait()
            async with asyncio.timeout(2):
                await signin.execute(
                    update(User).where(User.id == owner.id).values(last_login_at=func.now())
                )
                await signin.commit()
        finally:
            release.set()
        assert (await write).version == 2
