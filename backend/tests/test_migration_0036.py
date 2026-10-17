"""Migration 0036 creates the external reference tables with their
constraints and indexes, cascades rows when a project is hard deleted
(the assets stay), and downgrades cleanly.

Runs the real migrations on a scratch database, like test_migration_0034.
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from tests.test_schema_drift import _alembic, _recreate

TABLES = {"asset_external_refs", "project_external_refs", "project_key_documents"}
INDEXES = {
    "uq_asset_external_ref",
    "ix_asset_external_refs_lookup",
    "ix_asset_external_refs_created_by",
    "uq_project_external",
    "ix_project_external_refs_created_by",
    "ix_project_key_documents_asset",
}


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


async def _tables(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    )
    return {r["table_name"] for r in rows}


async def _indexes(conn: asyncpg.Connection) -> set[str]:
    rows = await conn.fetch(
        "SELECT indexname FROM pg_indexes WHERE tablename = ANY($1::text[])", list(TABLES)
    )
    return {r["indexname"] for r in rows}


async def _mk_project(conn: asyncpg.Connection) -> UUID:
    project_id = uuid4()
    await conn.execute(
        "INSERT INTO projects (id, slug, name) VALUES ($1, $2, 'p')",
        project_id,
        project_id.hex[:32],
    )
    return project_id


async def _mk_asset(conn: asyncpg.Connection, owner: UUID, project: UUID | None) -> UUID:
    asset_id = uuid4()
    await conn.execute(
        "INSERT INTO assets (id, slug, owner_id, kind, storage_prefix, project_id)"
        " VALUES ($1, $2, $3, 'md_single', $4, $5)",
        asset_id,
        asset_id.hex[:32],
        owner,
        f"assets/{asset_id}",
        project,
    )
    return asset_id


async def _ref(
    conn: asyncpg.Connection,
    asset: UUID,
    *,
    system: str = "openproject",
    entity: str = "work_package",
    role: str = "context",
    origin: str = "manual",
    asset_path: str | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO asset_external_refs"
        " (id, asset_id, system, entity, external_id, role, origin, asset_path)"
        " VALUES ($1, $2, $3, $4, '4711', $5, $6, $7)",
        uuid4(),
        asset,
        system,
        entity,
        role,
        origin,
        asset_path,
    )


async def _count(conn: asyncpg.Connection, table: str, column: str, value: UUID) -> int:
    return await conn.fetchval(f"SELECT count(*) FROM {table} WHERE {column} = $1", value)


async def _check_constraints_and_cascade(url: str) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        assert await _tables(conn) >= TABLES
        assert await _indexes(conn) >= INDEXES

        user_id = uuid4()
        await conn.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", user_id, f"{user_id}@example.com"
        )
        project, other = await _mk_project(conn), await _mk_project(conn)
        asset = await _mk_asset(conn, user_id, other)

        await _ref(conn, asset)
        assert (
            await conn.fetchval(
                "SELECT required FROM asset_external_refs WHERE asset_id = $1", asset
            )
            is False
        )
        # NULL paths collapse through coalesce, so the same link cannot repeat...
        with pytest.raises(asyncpg.UniqueViolationError):
            await _ref(conn, asset, origin="agent")
        # ...while another role or another file of a collection is a different link.
        await _ref(conn, asset, role="deliverable")
        await _ref(conn, asset, asset_path="annex.md")

        for bad in ({"system": "jira"}, {"entity": "issue"}, {"role": "input"}, {"origin": "x"}):
            with pytest.raises(asyncpg.CheckViolationError):
                await _ref(conn, asset, **bad)

        await conn.execute(
            "INSERT INTO project_external_refs (project_id, system, external_id)"
            " VALUES ($1, 'openproject', 'website')",
            project,
        )
        # One ICS project is the only home of an external project.
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO project_external_refs (project_id, system, external_id)"
                " VALUES ($1, 'openproject', 'website')",
                other,
            )
        await conn.execute(
            "INSERT INTO project_key_documents (project_id, asset_id, position, reason)"
            " VALUES ($1, $2, 0, 'charter')",
            project,
            asset,
        )

        await conn.execute("DELETE FROM projects WHERE id = $1", project)
        assert await _count(conn, "project_external_refs", "project_id", project) == 0
        assert await _count(conn, "project_key_documents", "project_id", project) == 0
        assert await _count(conn, "assets", "id", asset) == 1
        assert await _count(conn, "asset_external_refs", "asset_id", asset) == 3

        await conn.execute("DELETE FROM assets WHERE id = $1", asset)
        assert await _count(conn, "asset_external_refs", "asset_id", asset) == 0
    finally:
        await conn.close()


async def _check_dropped(url: str) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        assert not (await _tables(conn) & TABLES)
    finally:
        await conn.close()


def test_upgrade_creates_external_ref_tables_cascades_and_downgrades():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_mig0036_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))

    step = _alembic("upgrade", "0035", url=url)
    assert step.returncode == 0, step.stderr
    step = _alembic("upgrade", "0036", url=url)
    assert step.returncode == 0, step.stderr

    asyncio.run(_check_constraints_and_cascade(url))

    step = _alembic("downgrade", "0035", url=url)
    assert step.returncode == 0, step.stderr
    asyncio.run(_check_dropped(url))
