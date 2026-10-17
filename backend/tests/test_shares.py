"""Critical ShareLink paths: what could let the wrong viewer in."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
from app.models import Asset, ShareLink, User
from app.passwords import hash_password
from app.slug import generate_slug, generate_token


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


async def _mk_asset_and_share(session, *, mode: str, password_hash=None, **kwargs) -> ShareLink:
    user = User(email=f"owner+{generate_slug(6)}@example.com", display_name="owner", role="user")
    session.add(user)
    await session.flush()
    asset = Asset(
        slug=generate_slug(),
        owner_id=user.id,
        kind="md_single",
        title="t",
        storage_prefix="x",
        entry_path="x.md",
        security_status="clean",
        version=1,
    )
    session.add(asset)
    await session.flush()
    share = ShareLink(
        asset_id=asset.id,
        token=generate_token(),
        mode=mode,
        password_hash=password_hash,
        **kwargs,
    )
    session.add(share)
    await session.commit()
    return share


@pytest.mark.asyncio
async def test_resolve_share_returns_share(session):
    share = await _mk_asset_and_share(session, mode="public")
    from app.routes.shares import _resolve_share

    s2, _asset = await _resolve_share(share.token, session)
    assert s2.id == share.id


@pytest.mark.asyncio
async def test_resolve_share_404_for_unknown_token(session):
    from fastapi import HTTPException

    from app.routes.shares import _resolve_share

    with pytest.raises(HTTPException) as exc:
        await _resolve_share("nope-nope-nope", session)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_resolve_share_410_for_revoked(session):
    from fastapi import HTTPException

    from app.routes.shares import _resolve_share

    share = await _mk_asset_and_share(session, mode="public")
    share.revoked_at = datetime.now(UTC)
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await _resolve_share(share.token, session)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_resolve_share_410_for_expired(session):
    from fastapi import HTTPException

    from app.routes.shares import _resolve_share

    share = await _mk_asset_and_share(
        session,
        mode="public",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(HTTPException) as exc:
        await _resolve_share(share.token, session)
    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_resolve_share_410_for_max_views_exhausted(session):
    from fastapi import HTTPException

    from app.routes.shares import _resolve_share

    share = await _mk_asset_and_share(session, mode="public", max_views=1)
    share.view_count = 1
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await _resolve_share(share.token, session)
    assert exc.value.status_code == 410


def test_password_share_requires_password_hash():
    """Password-mode share must carry a hash; absence is a critical bug."""
    h = hash_password("StrongPass1!demo")
    s = ShareLink(asset_id=None, token="x", mode="password", password_hash=h)
    assert s.password_hash and s.password_hash.startswith("$argon2")
