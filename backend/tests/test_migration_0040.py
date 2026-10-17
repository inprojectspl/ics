"""Migration 0040 adds the generated `assets.content_hash`, fills it for
existing rows, and downgrades cleanly. Runs the real migrations on a scratch
database, like test_migration_search_tsv."""

from __future__ import annotations

import asyncio
import hashlib
import os
from uuid import uuid4

import asyncpg

from tests.test_schema_drift import _alembic, _recreate


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _seed(url: str):
    conn = await asyncpg.connect(_dsn(url))
    try:
        user_id, asset_id = uuid4(), uuid4()
        await conn.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", user_id, f"{user_id}@example.com"
        )
        await conn.execute(
            "INSERT INTO assets (id, slug, owner_id, kind, storage_prefix, title, search_content)"
            " VALUES ($1, $2, $3, 'md_single', $4, 't', '  Same   TEXT ')",
            asset_id,
            asset_id.hex[:32],
            user_id,
            f"assets/{asset_id}",
        )
        return asset_id
    finally:
        await conn.close()


async def _hash(url: str, asset_id) -> str | None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        return await conn.fetchval("SELECT content_hash FROM assets WHERE id = $1", asset_id)
    finally:
        await conn.close()


async def _schema(url: str) -> tuple[bool, bool]:
    conn = await asyncpg.connect(_dsn(url))
    try:
        column = await conn.fetchval(
            "SELECT 1 FROM information_schema.columns"
            " WHERE table_name = 'assets' AND column_name = 'content_hash'"
        )
        function = await conn.fetchval("SELECT 1 FROM pg_proc WHERE proname = 'ics_content_hash'")
        return bool(column), bool(function)
    finally:
        await conn.close()


def test_upgrade_fills_content_hash_and_downgrades():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_mig0040_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))

    step = _alembic("upgrade", "0039", url=url)
    assert step.returncode == 0, step.stderr
    asset_id = asyncio.run(_seed(url))

    step = _alembic("upgrade", "0040", url=url)
    assert step.returncode == 0, step.stderr
    assert asyncio.run(_hash(url, asset_id)) == hashlib.sha256(b"same text").hexdigest()

    step = _alembic("downgrade", "0039", url=url)
    assert step.returncode == 0, step.stderr
    assert asyncio.run(_schema(url)) == (False, False)
