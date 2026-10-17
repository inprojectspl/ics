"""Owner-side asset search.

Covers (a) `search.compute_search_content` correctly concatenates .md
files and skips html_bundle, (b) the /search endpoint matches by title
and by indexed content, respects owner isolation and the soft-delete
filter.
"""

from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import search
from app.config import get_settings
from app.db import Base
from app.models import Asset, User
from app.routes.assets import search_my_assets
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


@pytest_asyncio.fixture
async def owner(session):
    u = User(email=f"o+{generate_slug(6)}@example.com", role="user")
    session.add(u)
    await session.flush()
    return u


def _write(prefix: Path, asset: Asset, version: int, files: dict[str, str]) -> int:
    base = prefix / asset.storage_prefix / f"v{version}"
    base.mkdir(parents=True, exist_ok=True)
    total = 0
    for rel, content in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8")
        p.write_bytes(data)
        total += len(data)
    return total


async def _fs_settings(tmp_path: Path):
    s = get_settings()
    return SimpleNamespace(
        storage_url=f"fs://{tmp_path}",
        **{k: getattr(s, k) for k in vars(s).keys() if k != "storage_url"},
    )


async def _mk_asset(
    session,
    *,
    owner: User,
    kind: str = "md_single",
    title: str | None = "doc",
    content: str | None = None,
) -> Asset:
    asset = Asset(
        id=uuid4(),
        slug=generate_slug(),
        owner_id=owner.id,
        kind=kind,
        title=title,
        storage_prefix=f"assets/{generate_slug(8)}",
        entry_path="notes.md" if kind == "md_single" else "README.md",
        security_status="clean",
        version=1,
        size_bytes=len((content or "").encode("utf-8")),
        search_content=content,
    )
    session.add(asset)
    await session.commit()
    return asset


@pytest.mark.asyncio
async def test_compute_concatenates_md_files(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, owner=owner, kind="md_collection")
    _write(
        tmp_path,
        asset,
        1,
        {
            "README.md": "alpha line\n",
            "Notes/page.md": "beta line\n",
            "README.txt": "should not be indexed\n",  # non-md
        },
    )
    settings = await _fs_settings(tmp_path)

    blob = await search.compute_search_content(asset, settings)

    assert "alpha line" in blob
    assert "beta line" in blob
    assert "should not be indexed" not in blob


@pytest.mark.asyncio
async def test_compute_skips_html_bundle(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, owner=owner, kind="html_bundle")
    settings = await _fs_settings(tmp_path)
    assert await search.compute_search_content(asset, settings) is None


@pytest.mark.asyncio
async def test_compute_returns_none_for_empty(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, owner=owner, kind="md_collection")
    _write(tmp_path, asset, 1, {"image.png": "binary"})  # no .md
    settings = await _fs_settings(tmp_path)
    assert await search.compute_search_content(asset, settings) is None


@pytest.mark.asyncio
async def test_search_matches_title(session, owner):
    await _mk_asset(session, owner=owner, title="Quarterly report 2026", content="x")
    await _mk_asset(session, owner=owner, title="Random unrelated doc", content="x")

    rows = await search_my_assets(owner, session, q="quarterly", limit=50)
    titles = [r["title"] for r in rows]
    assert "Quarterly report 2026" in titles
    assert "Random unrelated doc" not in titles


@pytest.mark.asyncio
async def test_search_matches_content(session, owner):
    await _mk_asset(
        session,
        owner=owner,
        title="meeting-notes",
        content="agenda:\n- deploy postgres\n- review migrations\n",
    )
    await _mk_asset(session, owner=owner, title="other", content="unrelated text")

    rows = await search_my_assets(owner, session, q="postgres", limit=50)
    assert [r["title"] for r in rows] == ["meeting-notes"]


@pytest.mark.asyncio
async def test_search_excludes_other_owners(session, owner):
    other = User(email=f"o+{generate_slug(6)}@example.com", role="user")
    session.add(other)
    await session.flush()
    await _mk_asset(session, owner=other, title="other-quarter", content="quarterly")

    rows = await search_my_assets(owner, session, q="quarterly", limit=50)
    assert rows == []


@pytest.mark.asyncio
async def test_search_excludes_soft_deleted(session, owner):
    from datetime import datetime

    asset = await _mk_asset(session, owner=owner, title="soft-deleted", content="findme")
    asset.deleted_at = datetime.now(UTC)
    await session.commit()

    rows = await search_my_assets(owner, session, q="findme", limit=50)
    assert rows == []


@pytest.mark.asyncio
async def test_search_case_insensitive(session, owner):
    await _mk_asset(session, owner=owner, title="t", content="UPPERCASE keyword")

    rows = await search_my_assets(owner, session, q="uppercase", limit=50)
    assert len(rows) == 1
