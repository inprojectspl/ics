"""Security test for `permissions.get_owned_asset_by_slug` (editor+).

The gate keeps a caller who only knows the slug from bypassing ShareLink
protection, and answers 404 to prevent enumeration. Write paths use this
helper; read endpoints use `get_viewable_asset_by_slug` (viewer-level), covered
in test_view_access_roles.py.
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
from app.domain_errors import DomainError
from app.errors import domain_status
from app.models import Asset, User
from app.permissions import get_owned_asset_by_slug as _get_owned_asset_or_403
from app.slug import generate_slug


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


async def _mk_asset(session) -> tuple[User, Asset]:
    owner = User(email=f"o+{generate_slug(6)}@example.com", display_name="owner", role="user")
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
    await session.commit()
    return owner, asset


@pytest.mark.asyncio
async def test_owner_gets_asset(session):
    owner, asset = await _mk_asset(session)
    out = await _get_owned_asset_or_403(session, asset.slug, owner)
    assert out.id == asset.id


@pytest.mark.asyncio
async def test_non_owner_user_gets_404(session):
    _, asset = await _mk_asset(session)
    intruder = User(email=f"i+{generate_slug(6)}@example.com", display_name="intruder", role="user")
    session.add(intruder)
    await session.flush()
    with pytest.raises(DomainError) as exc:
        await _get_owned_asset_or_403(session, asset.slug, intruder)
    # 404 (not 403): must not leak slug existence.
    assert domain_status(exc.value) == 404


@pytest.mark.asyncio
async def test_external_role_gets_404(session):
    _, asset = await _mk_asset(session)
    client = User(
        email=f"c+{generate_slug(6)}@example.com",
        display_name="client",
        role="external",
    )
    session.add(client)
    await session.flush()
    with pytest.raises(DomainError) as exc:
        await _get_owned_asset_or_403(session, asset.slug, client)
    assert domain_status(exc.value) == 404


@pytest.mark.asyncio
async def test_admin_bypasses_ownership(session):
    _, asset = await _mk_asset(session)
    admin = User(email=f"a+{generate_slug(6)}@example.com", display_name="admin", role="admin")
    session.add(admin)
    await session.flush()
    out = await _get_owned_asset_or_403(session, asset.slug, admin)
    assert out.id == asset.id


@pytest.mark.asyncio
async def test_unknown_slug_404(session):
    owner, _ = await _mk_asset(session)
    with pytest.raises(DomainError) as exc:
        await _get_owned_asset_or_403(session, "does-not-exist", owner)
    assert domain_status(exc.value) == 404
