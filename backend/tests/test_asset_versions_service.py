"""`services.asset_versions.commit_new_version`, tested without HTTP.

Every version-producing endpoint goes through this function, so the
invariants live here: the bump, carry-over of untouched files, the owner's
quota, and that any failure leaves the current version as it was.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.collections_io import list_version_files, read_bytes_at_version
from app.config import get_settings
from app.domain_errors import ConflictError
from app.models import Asset, AssetShare, AssetVersion, AuditLog, User
from app.quota import QuotaExceededError
from app.services import asset_versions, publications
from tests.conftest import mk_asset, mk_user, put_blob

pytestmark = pytest.mark.usefixtures("fs_storage")


async def _vault(session, owner: User, files: dict[str, bytes]) -> Asset:
    asset = await mk_asset(session, owner, kind="md_collection", entry_path="index.md")
    for rel, data in files.items():
        await put_blob(asset, rel, data)
    asset.size_bytes = sum(len(d) for d in files.values())
    await session.commit()
    return asset


async def _tree(asset: Asset, version: int) -> dict[str, bytes]:
    settings = get_settings()
    return {
        rel: await read_bytes_at_version(asset, version, rel, settings)
        for rel in await list_version_files(asset, version, settings)
    }


async def _versions(session, asset: Asset) -> list[int]:
    rows = await session.execute(
        select(AssetVersion.version).where(AssetVersion.asset_id == asset.id)
    )
    return sorted(rows.scalars())


async def _commit(session, asset, user, stage, action="test_versioned"):
    return await asset_versions.commit_new_version(
        session,
        asset,
        get_settings(),
        stage=stage,
        actor=user,
        created_by=user.id,
        audit_action=action,
        audit_payload=lambda nv: {"version": nv.version},
    )


@pytest.mark.asyncio
async def test_edit_bumps_version_and_carries_untouched_files(session):
    owner = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"# a", "notes/b.md": b"bb"})

    result = await _commit(
        session,
        asset,
        owner,
        asset_versions.edit_files(put={"index.md": b"# edited"}),
    )

    assert result.version == 2
    assert asset.version == 2
    assert asset.size_bytes == 3 + 2 + 5
    assert await _tree(asset, 2) == {"index.md": b"# edited", "notes/b.md": b"bb"}
    # The previous tree is history and stays byte-for-byte as it was.
    assert await _tree(asset, 1) == {"index.md": b"# a", "notes/b.md": b"bb"}
    assert await _versions(session, asset) == [2]
    audit = (
        await session.execute(select(AuditLog).where(AuditLog.target == f"asset:{asset.id}"))
    ).scalar_one()
    assert audit.action == "test_versioned"
    assert audit.payload == {"version": 2}


@pytest.mark.asyncio
async def test_delete_and_entry_change(session):
    owner = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"i", "other.md": b"o"})

    result = await _commit(
        session,
        asset,
        owner,
        asset_versions.edit_files(delete=["index.md"], entry_path="other.md"),
    )

    assert result.entry_path == "other.md"
    assert asset.entry_path == "other.md"
    assert await _tree(asset, 2) == {"other.md": b"o"}


@pytest.mark.asyncio
async def test_quota_refusal_leaves_the_current_version_intact(session):
    owner = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"12345"})
    owner.storage_quota_bytes = 8
    await session.commit()

    with pytest.raises(QuotaExceededError):
        await _commit(
            session,
            asset,
            owner,
            asset_versions.edit_files(put={"big.md": b"x" * 10}),
        )
    await session.rollback()

    await session.refresh(asset)
    assert asset.version == 1
    assert asset.size_bytes == 5
    assert await _versions(session, asset) == []
    assert await _tree(asset, 2) == {}
    assert await _tree(asset, 1) == {"index.md": b"12345"}


@pytest.mark.asyncio
async def test_failing_stage_removes_the_partial_tree(session):
    owner = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"keep"})

    async def half_written(draft):
        await draft.storage.copy_prefix(draft.base_prefix, draft.prefix)
        raise RuntimeError("storage went away")

    with pytest.raises(RuntimeError):
        await _commit(session, asset, owner, half_written)
    await session.rollback()

    await session.refresh(asset)
    assert asset.version == 1
    assert await _tree(asset, 2) == {}
    assert await _tree(asset, 1) == {"index.md": b"keep"}


@pytest.mark.asyncio
async def test_leftovers_of_a_crashed_attempt_do_not_leak_in(session):
    owner = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"i"})
    # A process killed after writing v2 but before the commit.
    await put_blob(asset, "ghost.md", b"ghost", version=2)

    await _commit(session, asset, owner, asset_versions.edit_files(put={"new.md": b"n"}))

    assert await _tree(asset, 2) == {"index.md": b"i", "new.md": b"n"}


@pytest.mark.asyncio
async def test_shrinking_is_allowed_over_quota(session):
    owner = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"i", "big.md": b"x" * 20})
    owner.storage_quota_bytes = 5  # an admin lowered the quota below usage
    await session.commit()

    result = await _commit(session, asset, owner, asset_versions.edit_files(delete=["big.md"]))

    assert result.version == 2
    assert asset.size_bytes == 1


@pytest.mark.asyncio
async def test_growth_is_charged_to_the_owner_not_the_editor(session):
    owner = await mk_user(session)
    editor = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"i"})
    session.add(AssetShare(asset_id=asset.id, user_id=editor.id, role="editor"))
    editor.storage_quota_bytes = 10**9
    owner.storage_quota_bytes = 3
    await session.commit()

    with pytest.raises(QuotaExceededError):
        await _commit(
            session,
            asset,
            editor,
            asset_versions.edit_files(put={"more.md": b"xyz"}),
        )
    await session.rollback()

    # An editor with an exhausted quota may still grow the owner's asset.
    owner.storage_quota_bytes = 10**9
    editor.storage_quota_bytes = 0
    await session.commit()
    result = await _commit(
        session,
        asset,
        editor,
        asset_versions.edit_files(put={"more.md": b"xyz"}),
    )
    assert result.version == 2


@pytest.mark.asyncio
async def test_restore_of_a_bundle_respects_the_bundle_cap(session):
    owner = await mk_user(session)
    asset = await mk_asset(session, owner, kind="html_bundle", entry_path="index.html")
    await put_blob(asset, "index.html", b"<html>" + b"x" * 50)
    asset.size_bytes = 56
    owner.bundle_max_bytes = 40
    await session.commit()

    with pytest.raises(QuotaExceededError) as exc:
        await _commit(
            session,
            asset,
            owner,
            asset_versions.copy_version(f"{asset.storage_prefix}/v1"),
        )
    assert exc.value.code == "bundle_too_large"
    await session.rollback()
    await session.refresh(asset)
    assert asset.version == 1
    assert await _tree(asset, 2) == {}


@pytest.mark.asyncio
async def test_concurrent_expected_version_has_one_winner(session):
    owner = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"original"})
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    reached, release = asyncio.Event(), asyncio.Event()
    async with factory() as first, factory() as second:
        first_asset = await first.get(Asset, asset.id)
        second_asset = await second.get(Asset, asset.id)
        first_owner = await first.get(User, owner.id)
        second_owner = await second.get(User, owner.id)
        second_pid = await second.scalar(text("SELECT pg_backend_pid()"))
        assert first_asset.version == second_asset.version == 1

        async def winning_stage(draft):
            reached.set()
            await release.wait()
            return await asset_versions.edit_files(put={"index.md": b"winner"})(draft)

        async def losing_stage(draft):
            pytest.fail("a stale write must not stage files")

        async def commit(current, current_asset, current_owner, stage):
            return await asset_versions.commit_new_version(
                current,
                current_asset,
                get_settings(),
                stage=stage,
                actor=current_owner,
                audit_action="expected_version_test",
                audit_payload=lambda nv: {"version": nv.version},
                expected_version=1,
            )

        winner = asyncio.create_task(commit(first, first_asset, first_owner, winning_stage))
        staged = asyncio.create_task(reached.wait())
        loser = None
        try:
            done, _ = await asyncio.wait(
                {winner, staged}, timeout=5, return_when=asyncio.FIRST_COMPLETED
            )
            if winner in done:
                await winner
            assert staged in done, "the first writer must hold the asset row lock"
            loser = asyncio.create_task(commit(second, second_asset, second_owner, losing_stage))
            async with asyncio.timeout(5):
                while not await session.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                    {"pid": second_pid},
                ):
                    if loser.done():
                        await loser
                    await asyncio.sleep(0.01)
            release.set()
            assert (await winner).version == 2
            with pytest.raises(ConflictError) as error:
                await loser
            assert error.value.code == "version_conflict"
            await second.rollback()
        finally:
            release.set()
            tasks = [winner, staged] + ([loser] if loser else [])
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    await session.refresh(asset)
    assert asset.version == 2
    assert await _versions(session, asset) == [2]
    assert await _tree(asset, 1) == {"index.md": b"original"}
    assert await _tree(asset, 2) == {"index.md": b"winner"}
    assert await _tree(asset, 3) == {}
    audits = (
        await session.scalars(select(AuditLog).where(AuditLog.target == f"asset:{asset.id}"))
    ).all()
    assert [audit.payload for audit in audits] == [{"version": 2}]


@pytest.mark.asyncio
async def test_expected_version_conflict_precedes_storage_cleanup(session):
    owner = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"original"})
    await _commit(session, asset, owner, asset_versions.edit_files(put={"index.md": b"current"}))
    # Even a leftover staging tree must remain untouched when the precondition fails.
    await put_blob(asset, "leftover.md", b"untouched", version=3)
    with pytest.raises(ConflictError) as error:
        await asset_versions.commit_new_version(
            session,
            asset,
            get_settings(),
            stage=asset_versions.edit_files(put={"index.md": b"stale"}),
            actor=owner,
            audit_action="must_not_be_recorded",
            audit_payload=lambda nv: {"version": nv.version},
            expected_version=1,
        )
    assert error.value.code == "version_conflict"
    await session.rollback()
    await session.refresh(asset)
    assert asset.version == 2
    assert await _versions(session, asset) == [2]
    assert await _tree(asset, 1) == {"index.md": b"original"}
    assert await _tree(asset, 2) == {"index.md": b"current"}
    assert await _tree(asset, 3) == {"leftover.md": b"untouched"}
    audits = (
        await session.scalars(select(AuditLog).where(AuditLog.target == f"asset:{asset.id}"))
    ).all()
    assert [audit.action for audit in audits] == ["test_versioned"]


@pytest.mark.asyncio
async def test_publication_replay_precedes_cas_and_does_not_stage_again(session):
    owner = await mk_user(session)
    asset = await _vault(session, owner, {"index.md": b"one"})
    scope = publications.PublicationScope(owner.id, None, "order", "report", "version-retry")
    intent = publications.VersionPublication(scope, publications.canonical_hash({"body": "two"}))
    staged = 0

    async def stage(draft):
        nonlocal staged
        staged += 1
        return await asset_versions.edit_files(put={"index.md": b"two"})(draft)

    async def publish():
        return await asset_versions.commit_new_version(
            session,
            asset,
            get_settings(),
            stage=stage,
            actor=owner,
            audit_action="test_publication",
            audit_payload=lambda nv: {"version": nv.version},
            expected_version=1,
            publication=intent,
        )

    first = await publish()
    second = await publish()
    assert first.version == second.version == 2
    assert first.publication_result == second.publication_result
    assert staged == 1
    assert await _versions(session, asset) == [2]
    assert await _tree(asset, 1) == {"index.md": b"one"}
    assert await _tree(asset, 2) == {"index.md": b"two"}
