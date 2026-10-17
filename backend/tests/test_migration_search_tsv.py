"""Migration 0038 switches `search_tsv` to the weighted expression (title and
summary A, tags B, content C) and downgrades back to the plain one.

Runs the real migrations on a scratch database, like test_migration_0034.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg

from tests.test_schema_drift import _alembic, _recreate


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _vector(conn: asyncpg.Connection, asset_id) -> str:
    return await conn.fetchval("SELECT search_tsv::text FROM assets WHERE id = $1", asset_id)


async def _mk_asset(conn: asyncpg.Connection) -> object:
    user_id, asset_id = uuid4(), uuid4()
    await conn.execute(
        "INSERT INTO users (id, email) VALUES ($1, $2)", user_id, f"{user_id}@example.com"
    )
    await conn.execute(
        "INSERT INTO assets (id, slug, owner_id, kind, storage_prefix, title, tags,"
        " search_content, summary)"
        " VALUES ($1, $2, $3, 'md_single', $4, 'heading', ARRAY['labelled'],"
        " 'body', 'gist')",
        asset_id,
        asset_id.hex[:32],
        user_id,
        f"assets/{asset_id}",
    )
    return asset_id


async def _has_index(conn: asyncpg.Connection) -> bool:
    return bool(
        await conn.fetchval("SELECT 1 FROM pg_indexes WHERE indexname = 'ix_assets_search_tsv'")
    )


async def _has_function(conn: asyncpg.Connection) -> bool:
    return bool(
        await conn.fetchval("SELECT 1 FROM pg_proc WHERE proname = 'ics_immutable_array_to_string'")
    )


async def _seed(url: str):
    conn = await asyncpg.connect(_dsn(url))
    try:
        asset_id = await _mk_asset(conn)
        assert await _vector(conn, asset_id) == "'body':2 'heading':1"
        return asset_id
    finally:
        await conn.close()


async def _check_weighted(url: str, asset_id) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        # Existing rows are recomputed by the rewrite.
        assert await _vector(conn, asset_id) == ("'body':4C 'gist':2A 'heading':1A 'labelled':3B")
        assert await _has_index(conn)
        assert await _has_function(conn)
    finally:
        await conn.close()


async def _check_plain(url: str, asset_id) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        assert await _vector(conn, asset_id) == "'body':2 'heading':1"
        assert await _has_index(conn)
        assert not await _has_function(conn)
    finally:
        await conn.close()


def test_upgrade_weights_search_vector_and_downgrades():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_migtsv_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))

    step = _alembic("upgrade", "0037", url=url)
    assert step.returncode == 0, step.stderr
    asset_id = asyncio.run(_seed(url))

    step = _alembic("upgrade", "0038", url=url)
    assert step.returncode == 0, step.stderr
    asyncio.run(_check_weighted(url, asset_id))

    step = _alembic("downgrade", "0037", url=url)
    assert step.returncode == 0, step.stderr
    asyncio.run(_check_plain(url, asset_id))
