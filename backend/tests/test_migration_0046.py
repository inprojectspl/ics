"""The database enforces publication identity and retains spent keys."""

import asyncio
import json
import os
from uuid import uuid4

import asyncpg
import pytest

from tests.test_migration_0036 import _dsn, _mk_asset
from tests.test_schema_drift import _alembic, _recreate


async def check_receipts(url):
    conn = await asyncpg.connect(_dsn(url))
    try:
        owner = uuid4()
        await conn.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", owner, f"{owner}@example.com"
        )
        asset = await _mk_asset(conn, owner, None)
        query = (
            "INSERT INTO publication_receipts "
            "(id, principal_id, project_id, order_id, role, publication_id, schema_version, payload_hash, asset_id, version, result) "
            "VALUES ($1,$2,$3,'order-1',$4,'pub-1',1,$5,$6,1,$7)"
        )
        result = json.dumps({"id": str(asset)})
        first = uuid4()
        await conn.execute(query, first, owner, None, "report", "a" * 64, asset, result)
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(query, uuid4(), owner, None, "report", "a" * 64, asset, result)
        await conn.execute(query, uuid4(), owner, None, "acceptance", "a" * 64, asset, result)
        await conn.execute(query, uuid4(), owner, uuid4(), "report", "a" * 64, asset, result)

        # No receipt survives a transaction whose asset creation rolled back.
        with pytest.raises(RuntimeError, match="synthetic rollback"):
            async with conn.transaction():
                rolled_asset = await _mk_asset(conn, owner, None)
                rolled_receipt = uuid4()
                await conn.execute(
                    query, rolled_receipt, owner, None, "rollback", "b" * 64, rolled_asset, result
                )
                raise RuntimeError("synthetic rollback")
        assert await conn.fetchval("SELECT count(*) FROM assets WHERE id=$1", rolled_asset) == 0
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM publication_receipts WHERE id=$1", rolled_receipt
            )
            == 0
        )

        await conn.execute("DELETE FROM assets WHERE id=$1", asset)
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM publication_receipts WHERE principal_id=$1", owner
            )
            == 3
        )
        assert (
            await conn.fetchval("SELECT asset_id FROM publication_receipts WHERE id=$1", first)
            is None
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(query, uuid4(), owner, None, "report", "a" * 64, None, result)
    finally:
        await conn.close()


def test_publication_receipt_migration_enforces_identity_and_atomicity():
    base = os.environ["ICS_DATABASE_URL"]
    name = f"ics_mig0046_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = base.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(base, name))
    step = _alembic("upgrade", "0045", url=url)
    assert step.returncode == 0, step.stderr
    step = _alembic("upgrade", "0046", url=url)
    assert step.returncode == 0, step.stderr
    asyncio.run(check_receipts(url))
    step = _alembic("downgrade", "0045", url=url)
    assert step.returncode == 0, step.stderr
    step = _alembic("upgrade", "head", url=url)
    assert step.returncode == 0, step.stderr
