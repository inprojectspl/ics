"""Existing micro-applications get stable short host names, reserved for good."""

import asyncio
import os
from uuid import uuid4

import asyncpg
import pytest

from app.slug import _ALPHABET
from tests.test_migration_0036 import _dsn, _mk_asset
from tests.test_schema_drift import _alembic, _recreate


async def _seed(url: str) -> list:
    conn = await asyncpg.connect(_dsn(url))
    try:
        owner = uuid4()
        await conn.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", owner, f"{owner}@example.com"
        )
        assets = [await _mk_asset(conn, owner, None) for _ in range(3)]
        for asset in assets:
            await conn.execute(
                "INSERT INTO microapp_environments (id, asset_id, environment, asset_hex) "
                "VALUES ($1, $2, 'prod', $3)",
                uuid4(),
                asset,
                asset.hex,
            )
        return assets
    finally:
        await conn.close()


async def _check(url: str, assets: list) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        rows = await conn.fetch(
            "SELECT e.asset_id, e.asset_hex, e.host_name, h.asset_id AS reserved_for "
            "FROM microapp_environments e JOIN microapp_host_names h ON h.name = e.host_name"
        )
        assert sorted(r["asset_id"] for r in rows) == sorted(assets)
        names = [r["host_name"] for r in rows]
        assert len(set(names)) == len(names)
        for r in rows:
            assert len(r["host_name"]) == 8 and set(r["host_name"]) <= set(_ALPHABET)
            assert r["reserved_for"] == r["asset_id"] and r["asset_hex"] == r["asset_id"].hex

        # A purged app keeps its reservation; its name cannot be taken again.
        gone = rows[0]
        await conn.execute("DELETE FROM assets WHERE id = $1", gone["asset_id"])
        assert (
            await conn.fetchval(
                "SELECT asset_id FROM microapp_host_names WHERE name = $1", gone["host_name"]
            )
            == gone["asset_id"]
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO microapp_host_names (name, asset_id, environment) "
                "VALUES ($1, $2, 'prod')",
                gone["host_name"],
                uuid4(),
            )
        # An environment cannot exist without a reserved name.
        with pytest.raises(asyncpg.NotNullViolationError):
            await conn.execute(
                "INSERT INTO microapp_environments (id, asset_id, environment, asset_hex) "
                "VALUES ($1, $2, 'prod', $3)",
                uuid4(),
                rows[1]["asset_id"],
                uuid4().hex,
            )
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "UPDATE microapp_environments SET host_name = 'zzzzzzzz' WHERE asset_id = $1",
                rows[1]["asset_id"],
            )
    finally:
        await conn.close()


def test_existing_apps_get_reserved_short_names():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_mig0051_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))
    step = _alembic("upgrade", "0050", url=url)
    assert step.returncode == 0, step.stderr
    assets = asyncio.run(_seed(url))
    step = _alembic("upgrade", "0051", url=url)
    assert step.returncode == 0, step.stderr
    asyncio.run(_check(url, assets))
    step = _alembic("downgrade", "0050", url=url)
    assert step.returncode == 0, step.stderr
