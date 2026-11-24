"""A sheet link of one tab becomes a link of the file with one mapping and
keeps its agreed values; an operation whose sheet write is unsettled can
still be checked after the upgrade (ADR-0033)."""

import asyncio
import json
import os
from uuid import UUID, uuid4

import asyncpg

from tests.test_migration_0036 import _dsn, _mk_asset
from tests.test_schema_drift import _alembic, _recreate

COLUMNS = [
    {"field": "title", "header": "Title", "owner": "both"},
    {"field": "status", "header": "Status", "owner": "app"},
]


async def _seed(url: str) -> dict[str, UUID]:
    conn = await asyncpg.connect(_dsn(url))
    try:
        owner = uuid4()
        await conn.execute(
            "INSERT INTO users (id, email) VALUES ($1, $2)", owner, f"{owner}@example.com"
        )
        asset = await _mk_asset(conn, owner, None)
        link, record = uuid4(), uuid4()
        await conn.execute(
            "INSERT INTO sheet_links (id, asset_id, collection, spreadsheet_id, sheet_title,"
            " key_field, columns, account_mode, revision) VALUES ($1, $2, 'requests', $3,"
            " 'Requests', 'title', $4::jsonb, 'owner_account', 3)",
            link,
            asset,
            "1Sheet" + uuid4().hex,
            json.dumps(COLUMNS),
        )
        await conn.execute(
            "INSERT INTO sheet_base (link_id, record_id, values, row) VALUES ($1, $2, $3::jsonb, 4)",
            link,
            record,
            json.dumps({"title": "Lamp", "status": "new"}),
        )
        preview = {
            "sheet": {"sheet_id": 7, "title": "Requests", "cols": {"title": 0, "status": 1}},
            "updates": [],
            "creates": [],
            "appends": [{"record_id": str(record), "values": {"title": "Lamp"}}],
            "converged": [],
            "issues": [],
            "rows": {},
            "snapshot": {},
            "summary": {"appends": 1},
            "release": "r1",
        }
        export = {
            "patches": [],
            "local_base": {},
            "remote_base": {str(record): {"~unconfirmed": False}},
            "rows": {},
            "created": {},
            "cells": [{"row": 5, "col": 0, "field": "title", "value": "Lamp"}],
            "remote_rows": {str(record): 5},
        }
        ops = {}
        for name, state, google, revision in (
            ("uncertain", "applied", "uncertain", 3),
            ("waiting", "previewed", "none", 3),
            ("done", "applied", "confirmed", 2),
        ):
            ops[name] = uuid4()
            await conn.execute(
                "INSERT INTO sheet_operations (id, link_id, link_revision, state, google_status,"
                " summary, preview, export) VALUES ($1, $2, $3, $4, $5, '{}'::jsonb,"
                " $6::jsonb, $7::jsonb)",
                ops[name],
                link,
                revision,
                state,
                google,
                json.dumps(preview),
                json.dumps(export),
            )
        return {"link": link, "record": record, **ops}
    finally:
        await conn.close()


async def _check(url: str, ids: dict[str, UUID]) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        (mapping,) = await conn.fetch("SELECT * FROM sheet_mappings")
        assert mapping["link_id"] == ids["link"] and mapping["collection"] == "requests"
        assert json.loads(mapping["tabs"]) == [{"sheet_id": 7, "title": "Requests"}]
        assert mapping["key_field"] == "title" and json.loads(mapping["columns"]) == COLUMNS
        base = await conn.fetchrow("SELECT * FROM sheet_base")
        assert base["mapping_id"] == mapping["id"] and base["record_id"] == ids["record"]
        assert (base["sheet_id"], base["row"]) == (7, 4)
        assert json.loads(base["values"]) == {"title": "Lamp", "status": "new"}

        ops = {
            r["id"]: r
            for r in await conn.fetch("SELECT id, state, preview, export FROM sheet_operations")
        }
        assert ops[ids["waiting"]]["state"] == "superseded"
        done = ops[ids["done"]]
        assert json.loads(done["preview"]) == {} and done["export"] is None
        unsettled = ops[ids["uncertain"]]
        mid = str(mapping["id"])
        preview = json.loads(unsettled["preview"])
        part = preview["mappings"][mid]
        assert preview["release"] == "r1" and part["collection"] == "requests"
        assert part["sheet"] == {
            "cols": {"title": 0, "status": 1},
            "tabs": [
                {"sheet_id": 7, "title": "Requests", "first": 0, "cols": {"title": 0, "status": 1}}
            ],
        }
        export = json.loads(unsettled["export"])
        assert export["cells"] == {mid: [[7, 5, 0, "title", "Lamp"]]}
        assert export["remote_rows"] == {mid: {str(ids["record"]): [7, 5]}}
        assert export["mappings"][mid]["remote_base"] == {
            str(ids["record"]): {"~unconfirmed": False}
        }

        cols = {
            r["column_name"]
            for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'sheet_links'"
            )
        }
        assert not cols & {"collection", "sheet_title", "key_field", "columns"}
    finally:
        await conn.close()


async def _check_downgraded(url: str, ids: dict[str, UUID]) -> None:
    conn = await asyncpg.connect(_dsn(url))
    try:
        link = await conn.fetchrow("SELECT * FROM sheet_links")
        assert (link["collection"], link["sheet_title"]) == ("requests", "Requests")
        base = await conn.fetchrow("SELECT * FROM sheet_base")
        assert base["link_id"] == ids["link"]
    finally:
        await conn.close()


def test_a_tab_link_becomes_a_file_link_with_one_mapping_and_keeps_its_base():
    root = os.environ["ICS_DATABASE_URL"]
    name = f"ics_mig0056_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"
    url = root.rsplit("/", 1)[0] + f"/{name}"
    asyncio.run(_recreate(root, name))
    step = _alembic("upgrade", "0055", url=url)
    assert step.returncode == 0, step.stderr
    ids = asyncio.run(_seed(url))
    step = _alembic("upgrade", "0056", url=url)
    assert step.returncode == 0, step.stderr
    asyncio.run(_check(url, ids))
    step = _alembic("downgrade", "0055", url=url)
    assert step.returncode == 0, step.stderr
    asyncio.run(_check_downgraded(url, ids))
