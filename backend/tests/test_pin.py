"""Pin/unpin: timestamp semantics + list order + idempotency + per-user isolation.

Pin endpoints operate on `asset_pins` rows (a per-user preference, not
global asset state); list_my_assets puts the caller's pins first and sorts
inside each group by the requested key. We exercise the route handlers
directly following the established pattern.
"""

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
from app.models import Asset, AssetShare, User
from app.routes.assets import list_my_assets, pin_asset, unpin_asset
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
    u = User(email=f"u+{generate_slug(6)}@example.com", role="user")
    session.add(u)
    await session.flush()
    return u


async def _mk_asset(session, owner: User, *, title: str) -> Asset:
    a = Asset(
        id=uuid4(),
        slug=generate_slug(),
        owner_id=owner.id,
        kind="md_single",
        title=title,
        storage_prefix=f"assets/{generate_slug(8)}",
        entry_path="x.md",
        security_status="clean",
        version=1,
        size_bytes=10,
    )
    session.add(a)
    await session.commit()
    return a


@pytest.mark.asyncio
async def test_pin_sets_timestamp(session):
    user = await _mk_user(session)
    asset = await _mk_asset(session, user, title="alpha")
    out = await pin_asset(asset.id, user, session)
    assert out["pinned_at"] is not None


@pytest.mark.asyncio
async def test_unpin_clears_timestamp(session):
    user = await _mk_user(session)
    asset = await _mk_asset(session, user, title="alpha")
    await pin_asset(asset.id, user, session)
    out = await unpin_asset(asset.id, user, session)
    assert out["pinned_at"] is None


@pytest.mark.asyncio
async def test_unpin_idempotent_when_already_unpinned(session):
    user = await _mk_user(session)
    asset = await _mk_asset(session, user, title="alpha")
    # Asset starts unpinned: the call must succeed silently rather
    # than 404 on the "double-click the pin icon" UX path.
    out = await unpin_asset(asset.id, user, session)
    assert out["pinned_at"] is None


@pytest.mark.asyncio
async def test_repin_refreshes_timestamp(session):
    user = await _mk_user(session)
    asset = await _mk_asset(session, user, title="alpha")
    first = await pin_asset(asset.id, user, session)
    # Wallclock advances at least 1 ms between commits; force a small
    # gap so the comparison is deterministic on faster CI hosts.
    await asyncio.sleep(0.01)
    second = await pin_asset(asset.id, user, session)
    assert second["pinned_at"] > first["pinned_at"]


@pytest.mark.asyncio
async def test_pinning_does_not_reorder_the_list(session):
    user = await _mk_user(session)
    older = await _mk_asset(session, user, title="older")
    await asyncio.sleep(0.01)
    _newer = await _mk_asset(session, user, title="newer")
    # Favourites have their own scope in the UI; the list keeps its sort.
    await pin_asset(older.id, user, session)
    rows = (await list_my_assets(user, session))["items"]
    titles = [r["title"] for r in rows]
    assert titles.index("newer") < titles.index("older")


async def _share(session, asset: Asset, user: User, *, role: str = "viewer") -> None:
    session.add(AssetShare(asset_id=asset.id, user_id=user.id, role=role))
    await session.commit()


def _pinned_at_of(rows: list[dict], asset_id) -> str | None:
    return next(r["pinned_at"] for r in rows if r["id"] == str(asset_id))


# ---------- Per-user isolation ----------


@pytest.mark.asyncio
async def test_owner_pin_invisible_for_shared_user(session):
    owner = await _mk_user(session)
    other = await _mk_user(session)
    asset = await _mk_asset(session, owner, title="shared")
    await _share(session, asset, other)

    await pin_asset(asset.id, owner, session)

    assert _pinned_at_of((await list_my_assets(owner, session))["items"], asset.id) is not None
    # The owner's pin must not show up as another user's pin.
    assert _pinned_at_of((await list_my_assets(other, session))["items"], asset.id) is None


@pytest.mark.asyncio
async def test_shared_viewer_pins_independently(session):
    owner = await _mk_user(session)
    other = await _mk_user(session)
    asset = await _mk_asset(session, owner, title="shared")
    await _share(session, asset, other, role="viewer")

    # A viewer may pin: a pin is a private preference, not an asset mutation.
    out = await pin_asset(asset.id, other, session)
    assert out["pinned_at"] is not None

    assert _pinned_at_of((await list_my_assets(other, session))["items"], asset.id) is not None
    assert _pinned_at_of((await list_my_assets(owner, session))["items"], asset.id) is None


@pytest.mark.asyncio
async def test_unpin_removes_only_own_pin(session):
    owner = await _mk_user(session)
    other = await _mk_user(session)
    asset = await _mk_asset(session, owner, title="shared")
    await _share(session, asset, other)

    await pin_asset(asset.id, owner, session)
    await pin_asset(asset.id, other, session)
    await unpin_asset(asset.id, other, session)

    # Unpin by `other` must not remove the owner's pin.
    assert _pinned_at_of((await list_my_assets(owner, session))["items"], asset.id) is not None
    assert _pinned_at_of((await list_my_assets(other, session))["items"], asset.id) is None
