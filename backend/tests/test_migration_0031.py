"""Migration 0031 repairs html-json version rows that pointed at the whole
asset tree instead of its v1 directory."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.models import AssetVersion
from tests.conftest import mk_asset, mk_user

_PATH = Path(__file__).parents[1] / "migrations/versions/0031_fix_html_json_version_prefix.py"
_spec = importlib.util.spec_from_file_location("migration_0031", _PATH)
assert _spec and _spec.loader
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


async def _version_row(session, asset, prefix: str, version: int = 1) -> AssetVersion:
    row = AssetVersion(asset_id=asset.id, version=version, storage_prefix=prefix)
    session.add(row)
    await session.commit()
    return row


async def _prefix(session, row_id) -> str:
    return await session.scalar(
        select(AssetVersion.storage_prefix).where(AssetVersion.id == row_id)
    )


@pytest.mark.asyncio
async def test_broken_v1_row_points_at_the_v1_tree(session):
    asset = await mk_asset(session, await mk_user(session), kind="html_bundle")
    broken = await _version_row(session, asset, asset.storage_prefix)

    await session.execute(text(migration.FIX_SQL))
    await session.commit()

    assert await _prefix(session, broken.id) == f"{asset.storage_prefix}/v1"


@pytest.mark.asyncio
async def test_correct_rows_are_left_alone(session):
    asset = await mk_asset(session, await mk_user(session), kind="html_bundle")
    v1 = await _version_row(session, asset, f"{asset.storage_prefix}/v1")
    v2 = await _version_row(session, asset, f"{asset.storage_prefix}/v2", version=2)

    await session.execute(text(migration.FIX_SQL))
    await session.commit()

    assert await _prefix(session, v1.id) == f"{asset.storage_prefix}/v1"
    assert await _prefix(session, v2.id) == f"{asset.storage_prefix}/v2"
