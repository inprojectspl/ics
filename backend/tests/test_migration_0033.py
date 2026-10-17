"""Migration 0033 adds the asset metadata columns and the seeded `doc_types`
vocabulary without breaking writes of the previous shape, and downgrades cleanly.

Runs the real migrations on a scratch database: the test database is built
from the ORM metadata and has no seed rows.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg

from tests.test_schema_drift import _alembic, _recreate

ASSET_COLUMNS = {
    "summary",
    "summary_source",
    "summary_version",
    "doc_type",
    "maintainer_id",
    "review_due_at",
    "reviewed_at",
    "reviewed_by",
    "language",
    "properties",
}
ASSET_INDEXES = {
    "ix_assets_maintainer_id",
    "ix_assets_reviewed_by",
    "ix_asset_project_doc_type",
    "ix_assets_review_due_at",
    "ix_asset_content_updated_id",
}


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _fetch(url: str, query: str) -> list[asyncpg.Record]:
    conn = await asyncpg.connect(_dsn(url))
    try:
        return await conn.fetch(query)
    finally:
        await conn.close()


async def _columns(url: str, table: str) -> set[str]:
    rows = await _fetch(
        url,
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'",
    )
    return {r["column_name"] for r in rows}


async def _indexes(url: str) -> set[str]:
    rows = await _fetch(url, "SELECT indexname FROM pg_indexes WHERE tablename = 'assets'")
    return {r["indexname"] for r in rows}


async def _tables(url: str) -> set[str]:
    rows = await _fetch(
        url, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    return {r["table_name"] for r in rows}


async def _insert_previous_shape(url: str) -> None:
    """Insert rows the way the 0032 image does, naming only the old columns."""
    user_id, asset_id = uuid4(), uuid4()
    conn = await asyncpg.connect(_dsn(url))
    try:
        await conn.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", user_id, f"{user_id}@example.com"
        )
        await conn.execute(
            "INSERT INTO assets (id, slug, owner_id, kind, storage_prefix)"
            " VALUES ($1, $2, $3, 'md_single', $4)",
            asset_id,
            asset_id.hex[:32],
            user_id,
            f"assets/{asset_id}",
        )
        await conn.execute(
            "INSERT INTO asset_versions (id, asset_id, version, storage_prefix, created_by)"
            " VALUES ($1, $2, 1, 'p', $3)",
            uuid4(),
            asset_id,
            user_id,
        )
        props = await conn.fetchval("SELECT properties FROM assets WHERE id = $1", asset_id)
    finally:
        await conn.close()
    assert props == "{}"


async def _check_rejects_unknown_summary_source(url: str) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        try:
            await conn.execute("UPDATE assets SET summary_source = 'robot'")
        except asyncpg.CheckViolationError:
            return
    finally:
        await conn.close()
    raise AssertionError("summary_source CHECK did not reject an unknown value")


def test_upgrade_adds_metadata_and_seeds_doc_types_then_downgrades():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_mig0033_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))

    step = _alembic("upgrade", "0032", url=url)
    assert step.returncode == 0, step.stderr
    step = _alembic("upgrade", "0033", url=url)
    assert step.returncode == 0, step.stderr

    assert ASSET_COLUMNS <= asyncio.run(_columns(url, "assets"))
    assert "change_note" in asyncio.run(_columns(url, "asset_versions"))
    assert ASSET_INDEXES <= asyncio.run(_indexes(url))
    asyncio.run(_insert_previous_shape(url))
    asyncio.run(_check_rejects_unknown_summary_source(url))

    rows = asyncio.run(
        _fetch(url, "SELECT key, label_pl, label_en, agent_hint, position FROM doc_types")
    )
    assert len(rows) == 14
    assert {r["key"] for r in rows} >= {"business_goals", "policy", "runbook", "presentation"}
    for r in rows:
        assert r["label_pl"].strip() and r["label_en"].strip()
        assert r["agent_hint"].strip() and r["agent_hint"].isascii()
    assert len({r["position"] for r in rows}) == 14

    step = _alembic("downgrade", "0032", url=url)
    assert step.returncode == 0, step.stderr
    assert not ASSET_COLUMNS & asyncio.run(_columns(url, "assets"))
    assert "change_note" not in asyncio.run(_columns(url, "asset_versions"))
    assert not ASSET_INDEXES & asyncio.run(_indexes(url))
    assert "doc_types" not in asyncio.run(_tables(url))
