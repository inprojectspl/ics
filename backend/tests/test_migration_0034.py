"""Migration 0034 creates `asset_relations` with its constraints and indexes,
cascades edges when either end is hard deleted, and downgrades cleanly.

Runs the real migrations on a scratch database, like test_migration_0033.
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from tests.test_schema_drift import _alembic, _recreate

INDEXES = {"uq_asset_relation", "ix_asset_relations_target", "ix_asset_relations_created_by"}


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _tables(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    return {r["table_name"] for r in rows}


async def _indexes(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch("SELECT indexname FROM pg_indexes WHERE tablename = 'asset_relations'")
    return {r["indexname"] for r in rows}


async def _mk_asset(conn: asyncpg.Connection, owner: UUID) -> UUID:
    asset_id = uuid4()
    await conn.execute(
        "INSERT INTO assets (id, slug, owner_id, kind, storage_prefix)"
        " VALUES ($1, $2, $3, 'md_single', $4)",
        asset_id,
        asset_id.hex[:32],
        owner,
        f"assets/{asset_id}",
    )
    return asset_id


async def _edge(
    conn: asyncpg.Connection,
    source: UUID,
    target: UUID,
    relation_type: str = "depends_on",
    origin: str = "manual",
    target_path: str | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO asset_relations"
        " (id, source_asset_id, target_asset_id, relation_type, origin, target_path)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        uuid4(),
        source,
        target,
        relation_type,
        origin,
        target_path,
    )


async def _count(conn: asyncpg.Connection, asset_id: UUID) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM asset_relations WHERE source_asset_id = $1 OR target_asset_id = $1",
        asset_id,
    )


async def _check_constraints_and_cascade(url: str) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        assert "asset_relations" in await _tables(conn)
        assert await _indexes(conn) >= INDEXES

        user_id = uuid4()
        await conn.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", user_id, f"{user_id}@example.com"
        )
        a, b, c = [await _mk_asset(conn, user_id) for _ in range(3)]

        await _edge(conn, a, b)
        await _edge(conn, c, a, "derived_from", "agent")
        # NULL paths collapse through coalesce, so the same edge cannot repeat...
        with pytest.raises(asyncpg.UniqueViolationError):
            await _edge(conn, a, b, origin="extracted")
        # ...while an edge into another file of the target is a different edge.
        await _edge(conn, a, b, target_path="annex.md")

        with pytest.raises(asyncpg.CheckViolationError):
            await _edge(conn, a, a)
        with pytest.raises(asyncpg.CheckViolationError):
            await _edge(conn, a, c, relation_type="blocks")
        with pytest.raises(asyncpg.CheckViolationError):
            await _edge(conn, a, c, origin="robot")

        assert await _count(conn, a) == 3
        await conn.execute("DELETE FROM assets WHERE id = $1", a)
        assert await _count(conn, a) == 0
        assert await _count(conn, b) == 0
        assert await _count(conn, c) == 0
    finally:
        await conn.close()


async def _check_dropped(url: str) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        assert "asset_relations" not in await _tables(conn)
    finally:
        await conn.close()


def test_upgrade_creates_relations_table_cascades_and_downgrades():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_mig0034_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))

    step = _alembic("upgrade", "0033", url=url)
    assert step.returncode == 0, step.stderr
    step = _alembic("upgrade", "0034", url=url)
    assert step.returncode == 0, step.stderr

    asyncio.run(_check_constraints_and_cascade(url))

    step = _alembic("downgrade", "0033", url=url)
    assert step.returncode == 0, step.stderr
    asyncio.run(_check_dropped(url))
