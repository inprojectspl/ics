"""Inline edit endpoint: PUT /api/assets/{id}/content.

The endpoint creates a new version atomically: copies prior tree forward
(for md_collection), writes new content for the edited file, persists
the size/version bump, audits. Tests exercise the routing function
directly, like test_version_diff.
"""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db import Base
from app.models import Asset, User
from app.routes.assets import EditContentIn, edit_content
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


async def _settings(tmp_path: Path):
    s = get_settings()
    return SimpleNamespace(
        storage_url=f"fs://{tmp_path}",
        **{k: getattr(s, k) for k in vars(s).keys() if k != "storage_url"},
    )


async def _mk_asset(session, *, kind: str, owner: User) -> Asset:
    asset = Asset(
        id=uuid4(),
        slug=generate_slug(),
        owner_id=owner.id,
        kind=kind,
        title="t",
        storage_prefix=f"assets/{generate_slug(8)}",
        entry_path="notes.md" if kind == "md_single" else "README.md",
        security_status="clean",
        version=1,
        size_bytes=0,
    )
    session.add(asset)
    await session.commit()
    return asset


# ---------- md_single ----------


@pytest.mark.asyncio
async def test_edit_md_single_bumps_version(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, kind="md_single", owner=owner)
    asset.size_bytes = _write(tmp_path, asset, 1, {"notes.md": "draft\n"})
    await session.commit()
    settings = await _settings(tmp_path)

    body = EditContentIn(content="final version\n", path=None)
    out = await edit_content(asset.id, body, owner, session, settings)

    assert out["version"] == 2
    assert out["path"] == "notes.md"
    # Verify the new version's file on disk
    new_file = tmp_path / asset.storage_prefix / "v2" / "notes.md"
    assert new_file.read_text() == "final version\n"
    # Old version untouched
    old_file = tmp_path / asset.storage_prefix / "v1" / "notes.md"
    assert old_file.read_text() == "draft\n"


@pytest.mark.asyncio
async def test_edit_rejects_unchanged_content(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, kind="md_single", owner=owner)
    _write(tmp_path, asset, 1, {"notes.md": "same\n"})
    settings = await _settings(tmp_path)

    with pytest.raises(HTTPException) as exc:
        await edit_content(
            asset.id,
            EditContentIn(content="same\n", path=None),
            owner,
            session,
            settings,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_edit_rejects_path_mismatch_for_md_single(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, kind="md_single", owner=owner)
    _write(tmp_path, asset, 1, {"notes.md": "x\n"})
    settings = await _settings(tmp_path)

    with pytest.raises(HTTPException) as exc:
        await edit_content(
            asset.id,
            EditContentIn(content="y\n", path="other.md"),
            owner,
            session,
            settings,
        )
    assert exc.value.status_code == 400


# ---------- md_collection ----------


@pytest.mark.asyncio
async def test_edit_collection_copies_rest_forward(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, kind="md_collection", owner=owner)
    asset.size_bytes = _write(
        tmp_path,
        asset,
        1,
        {
            "README.md": "intro\n",
            "Notes/page.md": "old page\n",
            "Notes/keep.md": "stable file\n",
        },
    )
    await session.commit()
    settings = await _settings(tmp_path)

    body = EditContentIn(content="new page text\n", path="Notes/page.md")
    out = await edit_content(asset.id, body, owner, session, settings)

    assert out["version"] == 2
    assert out["path"] == "Notes/page.md"
    new_root = tmp_path / asset.storage_prefix / "v2"
    # Edited file gets new content
    assert (new_root / "Notes/page.md").read_text() == "new page text\n"
    # Untouched files are copied forward
    assert (new_root / "README.md").read_text() == "intro\n"
    assert (new_root / "Notes/keep.md").read_text() == "stable file\n"


@pytest.mark.asyncio
async def test_edit_collection_requires_path(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, kind="md_collection", owner=owner)
    _write(tmp_path, asset, 1, {"README.md": "x\n"})
    settings = await _settings(tmp_path)

    with pytest.raises(HTTPException) as exc:
        await edit_content(
            asset.id,
            EditContentIn(content="y\n", path=None),
            owner,
            session,
            settings,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_edit_collection_unknown_path_404(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, kind="md_collection", owner=owner)
    _write(tmp_path, asset, 1, {"README.md": "x\n"})
    settings = await _settings(tmp_path)

    with pytest.raises(HTTPException) as exc:
        await edit_content(
            asset.id,
            EditContentIn(content="y\n", path="Missing/page.md"),
            owner,
            session,
            settings,
        )
    assert exc.value.status_code == 404


# ---------- html_bundle blocked ----------


@pytest.mark.asyncio
async def test_edit_rejects_html_bundle(tmp_path: Path, session, owner):
    asset = await _mk_asset(session, kind="html_bundle", owner=owner)
    settings = await _settings(tmp_path)

    with pytest.raises(HTTPException) as exc:
        await edit_content(
            asset.id,
            EditContentIn(content="x\n", path=None),
            owner,
            session,
            settings,
        )
    assert exc.value.status_code == 400
