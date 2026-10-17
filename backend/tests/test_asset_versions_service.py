"""`services.asset_versions.commit_new_version`, tested without HTTP.

Every version-producing endpoint goes through this function, so the
invariants live here: the bump, carry-over of untouched files, the owner's
quota, and that any failure leaves the current version as it was.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.collections_io import list_version_files, read_bytes_at_version
from app.config import get_settings
from app.models import Asset, AssetShare, AssetVersion, AuditLog, User
from app.quota import QuotaExceededError
from app.services import asset_versions
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
        asset_versions.edit_files(put={"index.md": b"# edited"}, size_delta=5),
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
        asset_versions.edit_files(delete=["index.md"], size_delta=-1, entry_path="other.md"),
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
            asset_versions.edit_files(put={"big.md": b"x" * 10}, size_delta=10),
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

    result = await _commit(
        session, asset, owner, asset_versions.edit_files(delete=["big.md"], size_delta=-20)
    )

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
            asset_versions.edit_files(put={"more.md": b"xyz"}, size_delta=3),
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
        asset_versions.edit_files(put={"more.md": b"xyz"}, size_delta=3),
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
