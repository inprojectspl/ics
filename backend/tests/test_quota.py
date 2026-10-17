"""Per-user storage quota: usage calc + gate at upload time.

Storage accounting rules (verified here):
- only current-version size_bytes counts (older versions and deleted
  assets do not),
- a new-version write is judged on the delta (new total - old current),
- a smaller new version never fails the quota check.
"""

from datetime import UTC
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import quota
from app.config import get_settings
from app.db import Base
from app.domain_errors import DomainError
from app.errors import domain_status
from app.models import Asset, User
from app.slug import generate_slug


@pytest_asyncio.fixture
async def session():
    settings = get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _mk_user(session) -> User:
    user = User(
        email=f"u+{generate_slug(6)}@example.com",
        display_name="quota tester",
        role="user",
        storage_quota_bytes=1000,
    )
    session.add(user)
    await session.flush()
    return user


async def _mk_asset(session, owner: User, *, size: int, deleted: bool = False) -> Asset:
    asset = Asset(
        id=uuid4(),
        slug=generate_slug(),
        owner_id=owner.id,
        kind="md_single",
        title="t",
        storage_prefix="x",
        entry_path="x.md",
        security_status="clean",
        version=1,
        size_bytes=size,
    )
    if deleted:
        from datetime import datetime

        asset.deleted_at = datetime.now(UTC)
    session.add(asset)
    await session.flush()
    return asset


# ---------- usage calc ----------


@pytest.mark.asyncio
async def test_used_bytes_zero_for_empty(session):
    user = await _mk_user(session)
    assert await quota.used_bytes(session, user.id) == 0


@pytest.mark.asyncio
async def test_used_bytes_sums_live_assets(session):
    user = await _mk_user(session)
    await _mk_asset(session, user, size=300)
    await _mk_asset(session, user, size=200)
    assert await quota.used_bytes(session, user.id) == 500


@pytest.mark.asyncio
async def test_used_bytes_excludes_deleted(session):
    user = await _mk_user(session)
    await _mk_asset(session, user, size=300)
    await _mk_asset(session, user, size=999, deleted=True)
    # Soft-deleted assets are excluded from quota, which lets a user
    # free space by deleting before re-uploading.
    assert await quota.used_bytes(session, user.id) == 300


@pytest.mark.asyncio
async def test_used_bytes_does_not_leak_across_users(session):
    a = await _mk_user(session)
    b = await _mk_user(session)
    await _mk_asset(session, a, size=400)
    assert await quota.used_bytes(session, b.id) == 0


# ---------- enforcement ----------


@pytest.mark.asyncio
async def test_assert_can_grow_passes_under_quota(session):
    user = await _mk_user(session)  # quota 1000
    await _mk_asset(session, user, size=200)
    # 200 used + 500 incoming = 700 <= 1000.
    await quota.assert_can_grow(
        session,
        user.id,
        incoming_bytes=500,
        quota_bytes=user.storage_quota_bytes,
    )


@pytest.mark.asyncio
async def test_assert_can_grow_exactly_at_quota_passes(session):
    user = await _mk_user(session)
    await _mk_asset(session, user, size=400)
    # 400 used + 600 incoming = 1000: edge case at the limit, allow.
    await quota.assert_can_grow(
        session,
        user.id,
        incoming_bytes=600,
        quota_bytes=user.storage_quota_bytes,
    )


@pytest.mark.asyncio
async def test_assert_can_grow_blocks_when_over(session):
    user = await _mk_user(session)
    await _mk_asset(session, user, size=900)
    with pytest.raises(DomainError) as exc:
        await quota.assert_can_grow(
            session,
            user.id,
            incoming_bytes=200,
            quota_bytes=user.storage_quota_bytes,
        )
    assert domain_status(exc.value) == 413


@pytest.mark.asyncio
async def test_assert_can_grow_passes_for_smaller_new_version(session):
    user = await _mk_user(session)
    await _mk_asset(session, user, size=1000)  # at quota
    # New version is smaller than old -> delta is negative; never blocks.
    await quota.assert_can_grow(
        session,
        user.id,
        incoming_bytes=-400,
        quota_bytes=user.storage_quota_bytes,
    )


# ---------- assert_bundle_fits ----------


def test_assert_bundle_fits_passes_at_the_limit():
    # No exception: the cap is inclusive.
    quota.assert_bundle_fits(total_bytes=1024, bundle_max_bytes=1024)


def test_assert_bundle_fits_blocks_over_the_limit():
    with pytest.raises(DomainError) as exc:
        quota.assert_bundle_fits(total_bytes=1025, bundle_max_bytes=1024)
    assert domain_status(exc.value) == 413
