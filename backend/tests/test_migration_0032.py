"""Migration 0032 adds `assets.content_updated_at` / `content_updated_by`,
backfills them from `asset_versions`, and downgrades cleanly.

Runs the real migrations on a scratch database: the test database is built
from the ORM metadata and already has the columns.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import asyncpg

from tests.test_schema_drift import _alembic, _recreate

T1 = datetime(2024, 1, 1, tzinfo=UTC)
T2 = datetime(2024, 6, 1, tzinfo=UTC)
T3 = datetime(2025, 3, 1, tzinfo=UTC)


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _seed(url: str) -> dict[str, UUID]:
    ids = {k: uuid4() for k in ("owner", "editor", "versioned", "authorless", "bare")}
    conn = await asyncpg.connect(_dsn(url))
    try:
        for key in ("owner", "editor"):
            await conn.execute(
                "INSERT INTO users (id, email) VALUES ($1, $2)", ids[key], f"{key}@example.com"
            )
        for key in ("versioned", "authorless", "bare"):
            await conn.execute(
                "INSERT INTO assets (id, slug, owner_id, kind, storage_prefix, created_at)"
                " VALUES ($1, $2, $3, 'md_single', $4, $5)",
                ids[key],
                key,
                ids["owner"],
                f"assets/{key}",
                T1,
            )
        versions = [
            ("versioned", 1, T1, ids["owner"]),
            ("versioned", 2, T3, ids["editor"]),
            ("versioned", 3, T2, ids["owner"]),  # out of order: the newest row wins
            ("authorless", 1, T2, None),
        ]
        for key, n, at, by in versions:
            await conn.execute(
                "INSERT INTO asset_versions (id, asset_id, version, storage_prefix, created_at,"
                " created_by) VALUES ($1, $2, $3, 'p', $4, $5)",
                uuid4(),
                ids[key],
                n,
                at,
                by,
            )
    finally:
        await conn.close()
    return ids


async def _content_fields(url: str) -> dict[UUID, tuple[datetime, UUID]]:
    conn = await asyncpg.connect(_dsn(url))
    try:
        rows = await conn.fetch("SELECT id, content_updated_at, content_updated_by FROM assets")
    finally:
        await conn.close()
    return {r["id"]: (r["content_updated_at"], r["content_updated_by"]) for r in rows}


async def _schema(url: str) -> tuple[set[str], set[str]]:
    conn = await asyncpg.connect(_dsn(url))
    try:
        columns = await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'assets'"
        )
        indexes = await conn.fetch("SELECT indexname FROM pg_indexes WHERE tablename = 'assets'")
    finally:
        await conn.close()
    return {r["column_name"] for r in columns}, {r["indexname"] for r in indexes}


def test_upgrade_backfills_from_versions_and_downgrade_drops_the_columns():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_mig0032_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))

    step = _alembic("upgrade", "0031", url=url)
    assert step.returncode == 0, step.stderr
    ids = asyncio.run(_seed(url))

    step = _alembic("upgrade", "0032", url=url)
    assert step.returncode == 0, step.stderr
    fields = asyncio.run(_content_fields(url))
    assert fields[ids["versioned"]] == (T3, ids["editor"])
    assert fields[ids["authorless"]] == (T2, ids["owner"])
    assert fields[ids["bare"]] == (T1, ids["owner"])
    columns, indexes = asyncio.run(_schema(url))
    assert {"content_updated_at", "content_updated_by"} <= columns
    assert "ix_assets_content_updated_by" in indexes

    step = _alembic("downgrade", "0031", url=url)
    assert step.returncode == 0, step.stderr
    columns, indexes = asyncio.run(_schema(url))
    assert not {"content_updated_at", "content_updated_by"} & columns
    assert "ix_assets_content_updated_by" not in indexes
