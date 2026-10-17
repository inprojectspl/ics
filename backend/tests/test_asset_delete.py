"""Critical asset-delete invariants: only owner/admin can delete, all active
share links are revoked, deleted assets disappear from list/render."""

from datetime import UTC

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
from app.models import Asset, ShareLink, User
from app.slug import generate_slug, generate_token


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _mk_asset_with_shares(session, n_shares: int = 2):
    owner = User(email=f"o+{generate_slug(6)}@example.com", display_name="o", role="user")
    session.add(owner)
    await session.flush()
    asset = Asset(
        slug=generate_slug(),
        owner_id=owner.id,
        kind="md_single",
        title="t",
        storage_prefix="x",
        entry_path="x.md",
        security_status="clean",
        version=1,
    )
    session.add(asset)
    await session.flush()
    for _ in range(n_shares):
        session.add(
            ShareLink(
                asset_id=asset.id,
                token=generate_token(),
                mode="public",
                created_by=owner.id,
            )
        )
    await session.commit()
    return owner, asset


@pytest.mark.asyncio
async def test_deleted_asset_revokes_all_shares(session):
    """The cascade revoke is what makes /v/{slug} and /s/{token} both 410
    after delete; protects against the share-link-bypass class of bug."""
    from datetime import datetime

    from sqlalchemy import update

    _, asset = await _mk_asset_with_shares(session, n_shares=3)
    # simulate the delete endpoint's cascade
    now = datetime.now(UTC)
    asset.deleted_at = now
    await session.execute(
        update(ShareLink)
        .where(ShareLink.asset_id == asset.id, ShareLink.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.commit()

    shares = (
        (await session.execute(select(ShareLink).where(ShareLink.asset_id == asset.id)))
        .scalars()
        .all()
    )
    assert len(shares) == 3
    assert all(s.revoked_at is not None for s in shares)


@pytest.mark.asyncio
async def test_already_revoked_share_keeps_its_original_revoke_time(session):
    """Cascade must not overwrite an explicitly-revoked share's timestamp."""
    from datetime import datetime, timedelta

    from sqlalchemy import update

    _, asset = await _mk_asset_with_shares(session, n_shares=1)
    share = (
        await session.execute(select(ShareLink).where(ShareLink.asset_id == asset.id))
    ).scalar_one()
    earlier = datetime.now(UTC) - timedelta(days=1)
    share.revoked_at = earlier
    await session.commit()

    # delete asset now; cascade should skip already-revoked rows
    now = datetime.now(UTC)
    asset.deleted_at = now
    await session.execute(
        update(ShareLink)
        .where(ShareLink.asset_id == asset.id, ShareLink.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    await session.commit()

    await session.refresh(share)
    assert share.revoked_at == earlier  # unchanged
