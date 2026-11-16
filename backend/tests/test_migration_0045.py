"""The scoped PS key preserves legacy links and refuses a lossy downgrade."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest

from tests.test_migration_0036 import _dsn, _mk_asset
from tests.test_schema_drift import _alembic, _recreate


async def _seed(url):
    conn = await asyncpg.connect(_dsn(url))
    try:
        owner = uuid4()
        await conn.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", owner, f"{owner}@example.com"
        )
        asset = await _mk_asset(conn, owner, None)
        for system, entity, key, scope in (
            ("project_standard", "node", "n-null", None),
            ("project_standard", "node", "n-empty", ""),
            ("project_standard", "node", "n-scoped", "project-a"),
            ("openproject", "work_package", "4711", ""),
            ("openproject", "work_package", "4712", "historic"),
        ):
            await conn.execute(
                "INSERT INTO asset_external_refs "
                "(id, asset_id, system, entity, external_id, external_scope, role, origin, required, pinned_version) "
                "VALUES ($1, $2, $3, $4, $5, $6, 'context', 'agent', true, 1)",
                uuid4(),
                asset,
                system,
                entity,
                key,
                scope,
            )
        return asset, [
            dict(row) for row in await conn.fetch("SELECT * FROM asset_external_refs ORDER BY id")
        ]
    finally:
        await conn.close()


async def _check(url, asset, before):
    conn = await asyncpg.connect(_dsn(url))
    try:
        assert "(asset_id)" in await conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname='ix_asset_external_refs_asset'"
        )
        after = [
            dict(row) for row in await conn.fetch("SELECT * FROM asset_external_refs ORDER BY id")
        ]
        assert after == [{**row, "external_scope": row["external_scope"] or None} for row in before]
        query = (
            "INSERT INTO asset_external_refs "
            "(id, asset_id, system, entity, external_id, external_scope, role, origin, asset_path) "
            "VALUES ($1, $2, $3, $4, $5, $6, 'context', 'manual', $7)"
        )
        # The database, independently of the service, separates PS project scopes.
        collision = uuid4()
        await conn.execute(
            query, collision, asset, "project_standard", "node", "n-scoped", "project-b", None
        )
        for system, entity, key, scope, path in (
            ("project_standard", "node", "n-scoped", "project-a", ""),
            ("project_standard", "node", "n-null", "", None),
            ("project_standard", "node", "n-empty", None, None),
            ("openproject", "work_package", "4711", "other", None),
            ("openproject", "work_package", "4712", None, None),
        ):
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(query, uuid4(), asset, system, entity, key, scope, path)
        return collision, [
            dict(row) for row in await conn.fetch("SELECT * FROM asset_external_refs ORDER BY id")
        ]
    finally:
        await conn.close()


async def _check_failed_downgrade(url, expected, collision):
    conn = await asyncpg.connect(_dsn(url))
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version") == "0045"
        assert [
            dict(row) for row in await conn.fetch("SELECT * FROM asset_external_refs ORDER BY id")
        ] == expected
        assert "external_scope" in await conn.fetchval(
            "SELECT indexdef FROM pg_indexes WHERE indexname='uq_asset_ps_node_ref'"
        )
        # Removing only the new test link makes downgrade representable again.
        await conn.execute("DELETE FROM asset_external_refs WHERE id=$1", collision)
    finally:
        await conn.close()


def test_scope_upgrade_preserves_links_and_downgrade_never_discards_collisions():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_mig0045_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))
    step = _alembic("upgrade", "0044", url=url)
    assert step.returncode == 0, step.stderr
    asset, before = asyncio.run(_seed(url))
    step = _alembic("upgrade", "0045", url=url)
    assert step.returncode == 0, step.stderr
    collision, expected = asyncio.run(_check(url, asset, before))
    step = _alembic("downgrade", "0044", url=url)
    assert step.returncode != 0
    assert "uq_asset_external_ref" in step.stderr
    asyncio.run(_check_failed_downgrade(url, expected, collision))
    step = _alembic("downgrade", "0044", url=url)
    assert step.returncode == 0, step.stderr
    step = _alembic("upgrade", "0045", url=url)
    assert step.returncode == 0, step.stderr
