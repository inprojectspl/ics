"""One app over a whole spreadsheet file (ADR-0033): several collections,
a collection split across tabs, a list the app only reads, the tab a row
is in, one read and one write for the whole file, and no second write
planned while an earlier one is unsettled."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.models import SheetMapping
from app.services.sheets import sync as sync_mod
from app.services.sheets import write as write_mod
from app.services.sheets.book import Sheet, Tab
from app.services.sheets.compare import compare
from tests import test_sheets
from tests.conftest import mk_user
from tests.test_microapps import (  # noqa: F401 (fixtures)
    EXAMPLES,
    _enabled,
    _plan_and_apply,
    _publish,
    apps_db,
    bearer,
    needs_pg,
)
from tests.test_sheets import FakeGoogle, _connect

fake_google = test_sheets.fake_google
fake_broker = test_sheets.fake_broker

ORDERS = {
    "fields": {
        "number": {"type": "string", "required": True, "maxLength": 20},
        "customer_code": {"type": "string", "maxLength": 20},
        "status": {"type": "enum", "values": ["new", "sent", "paid"], "default": "new"},
        "total": {"type": "integer"},
        "month": {"type": "string", "maxLength": 100},
    },
    "crud": {
        "list": {"permission": "requests.read", "rowScope": "all"},
        "get": {"permission": "requests.read", "rowScope": "all"},
        "create": {
            "permission": "requests.create",
            "rowScope": "all",
            "writeFields": ["number", "customer_code", "status", "total", "month"],
        },
        "update": {
            "permission": "requests.edit",
            "rowScope": "all",
            "writeFields": ["number", "customer_code", "status", "total", "month"],
        },
    },
    "indexes": [{"fields": ["number"], "unique": True}],
}
CUSTOMERS = {
    "fields": {
        "code": {"type": "string", "required": True, "maxLength": 20},
        "name": {"type": "string", "maxLength": 200},
    },
    "crud": {
        "list": {"permission": "requests.read", "rowScope": "all"},
        "create": {
            "permission": "requests.create",
            "rowScope": "all",
            "writeFields": ["code", "name"],
        },
        "update": {
            "permission": "requests.edit",
            "rowScope": "all",
            "writeFields": ["code", "name"],
        },
    },
}

OCT, NOV = "Orders 2026-10", "Orders 2026-11"
ORDER_HEADERS = ["Number", "Customer", "Status", "Total"]
ORDER_COLUMNS = [
    {"field": "number", "header": "Number", "owner": "both"},
    {"field": "customer_code", "header": "Customer", "owner": "both"},
    {"field": "status", "header": "Status", "owner": "both"},
    # Computed in the sheet: the app only reads it.
    {"field": "total", "header": "Total", "owner": "sheet"},
]
CUSTOMER_COLUMNS = [
    {"field": "code", "header": "Code", "owner": "sheet"},
    {"field": "name", "header": "Name", "owner": "sheet"},
]


def _shop(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    shutil.copytree(EXAMPLES / "requests", root)
    manifest = json.loads((root / "microapp.json").read_text())
    manifest["database"]["collections"]["orders"] = ORDERS
    manifest["database"]["collections"]["customers"] = CUSTOMERS
    (root / "microapp.json").write_text(json.dumps(manifest))
    return root


async def _shop_app(client, session, tmp_path: Path):
    owner = await mk_user(session)
    await session.commit()
    _, r = await _plan_and_apply(
        client, owner, root=_shop(tmp_path), key=f"k-{uuid.uuid4().hex[:12]}"
    )
    op = r.json()
    assert await _publish(session, op["operation_id"]) == "succeeded"
    return owner, op["asset_id"]


def _book(fake: FakeGoogle) -> None:
    """The file as a shop keeps it: orders by month, customers, a report."""
    for tab in (OCT, NOV):
        fake.add_tab(tab, ORDER_HEADERS)
    fake.add_tab("Customers", ["Code", "Name"])
    fake.add_tab("Summary", ["Month", "Revenue"])
    fake.set(2, 0, "Oct", "Summary")
    for row, values in enumerate([["A-1", "ACME", "sent", 120], ["A-2", "BOLT", "new", 80]], 2):
        for col, v in enumerate(values):
            fake.set(row, col, v, OCT)
    for col, v in enumerate(["B-1", "ACME", "new", 50]):
        fake.set(2, col, v, NOV)
    for row, values in enumerate([["ACME", "Acme Ltd"], ["BOLT", "Bolt sp. z o.o."]], 2):
        for col, v in enumerate(values):
            fake.set(row, col, v, "Customers")


def _link_body(fake: FakeGoogle, **orders: Any) -> dict[str, Any]:
    return {
        "spreadsheet": fake.SPREADSHEET,
        "account_mode": "owner_account",
        "mappings": [
            {
                "collection": "orders",
                "tabs": [OCT, NOV],
                "append_to": NOV,
                "key_field": "number",
                "tab_field": "month",
                "columns": ORDER_COLUMNS,
                **orders,
            },
            {"collection": "customers", "tabs": ["Customers"], "columns": CUSTOMER_COLUMNS},
        ],
    }


async def _linked_shop(client, session, fake_google, tmp_path):
    owner, asset_id = await _shop_app(client, session, tmp_path)
    await _connect(client, owner, fake_google)
    _book(fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    r = await client.put(url, json=_link_body(fake_google), headers=bearer(owner))
    assert r.status_code == 200, r.text
    return owner, url, r.json()


# ------------------------------------------------------------- pure parts


def _two_tabs(rows_a: list[list[Any]], rows_b: list[list[Any]]) -> Sheet:
    cols = {"number": 0, "status": 1}
    tabs = [
        Tab(10, "A", 100, 0, len(rows_a), {"number": 0, "status": 1}),
        Tab(20, "B", 100, len(rows_a), len(rows_b), {"number": 1, "status": 0}, append=True),
    ]
    return Sheet("UTC", tabs, cols, [*rows_a, *rows_b])


def _orders_mapping(**extra: Any) -> SheetMapping:
    return SheetMapping(
        id=uuid.uuid4(),
        collection="orders",
        tabs=[{"sheet_id": 10, "title": "A"}, {"sheet_id": 20, "title": "B", "append": True}],
        key_field="number",
        tab_field="month",
        columns=[
            {"field": "number", "header": "Number", "owner": "both"},
            {"field": "status", "header": "Status", "owner": "both"},
        ],
        **extra,
    )


FIELDS = {
    "number": {"type": "string", "maxLength": 20},
    "status": {"type": "string", "maxLength": 20},
    "month": {"type": "string", "maxLength": 100},
}
R1, R2 = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))


def test_rows_of_a_group_of_tabs_compare_as_one_list_with_their_tab_named():
    sheet = _two_tabs([["A-1", "new"]], [["B-1", "new"], ["A-2", "sent"]])
    assert sheet.at(3) == (sheet.tabs[1], 2)
    app = [{"id": R1, "revision": 1, "number": "A-2", "status": "sent", "month": "A"}]
    base = {R1: {"number": "A-2", "status": "sent", "month": "A"}}
    plan = compare(_orders_mapping(), FIELDS, sheet, app, base, new_id=lambda: R2)
    # A-2 moved from tab A to tab B by hand: the same record, its tab follows.
    (update,) = plan["updates"]
    assert update["record_id"] == R1 and update["import"] == {"month": "B"}
    assert {c["data"]["number"]: c["data"]["month"] for c in plan["creates"]} == {
        "A-1": "A",
        "B-1": "B",
    }


def test_a_key_twice_across_tabs_is_reported_not_guessed():
    sheet = _two_tabs([["A-1", "new"]], [["A-1", "sent"]])
    plan = compare(_orders_mapping(), FIELDS, sheet, [], {}, new_id=lambda: R2)
    assert plan["issues"] == [{"kind": "duplicate_key", "row": 3, "first_row": 2}]
    assert [c["data"]["number"] for c in plan["creates"]] == ["A-1"]


def test_a_new_record_goes_to_the_append_tab_and_one_without_its_key_nowhere():
    sheet = _two_tabs([["A-1", "new"]], [])
    app = [
        {"id": R1, "revision": 1, "number": "C-1", "status": "new", "month": None},
        {"id": R2, "revision": 1, "number": None, "status": "new", "month": None},
    ]
    plan = compare(_orders_mapping(), FIELDS, sheet, app, {}, new_id=lambda: "x")
    (append,) = plan["appends"]
    # The tab field is not a column: nothing is written for it.
    assert append["sheet_id"] == 20 and append["values"] == {"number": "C-1", "status": "new"}
    assert {"kind": "key_missing", "record_id": R2} in plan["issues"]


def test_a_list_the_app_only_reads_never_appends():
    mapping = _orders_mapping()
    mapping.columns = [{**c, "owner": "sheet"} for c in mapping.columns]
    sheet = _two_tabs([["A-1", "new"]], [])
    app = [{"id": R1, "revision": 1, "number": "LOCAL", "status": "new", "month": None}]
    plan = compare(mapping, FIELDS, sheet, app, {}, new_id=lambda: R2)
    assert plan["appends"] == [] and plan["issues"] == []
    assert [c["data"]["number"] for c in plan["creates"]] == ["A-1"]


# ---------------------------------------------------------------- the link


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_a_group_of_tabs_needs_a_key_and_a_tab_for_new_records(
    client, session, fake_google, tmp_path
):
    owner, asset_id = await _shop_app(client, session, tmp_path)
    url = f"/api/micro-applications/{asset_id}/sheets"
    _book(fake_google)

    async def put(**orders: Any) -> Any:
        return await client.put(url, json=_link_body(fake_google, **orders), headers=bearer(owner))

    r = await put(key_field=None)
    assert r.status_code == 400 and r.json()["code"] == "key_field_required"
    r = await put(append_to=None)
    assert r.status_code == 400 and r.json()["code"] == "append_tab_required"
    r = await put(append_to="Customers")
    assert r.status_code == 400 and r.json()["code"] == "append_tab_invalid"
    r = await put(tab_field="total")
    assert r.status_code == 400 and r.json()["code"] == "tab_field_invalid"
    r = await put(tabs=[OCT, "Customers"], append_to=OCT)
    assert r.status_code == 400 and r.json()["code"] == "sheet_tab_ambiguous"
    r = await put(tabs=[OCT, OCT])
    assert r.status_code == 400 and r.json()["code"] == "tab_duplicate"
    # A list the app only reads needs no tab for new records.
    read_only = [{**c, "owner": "sheet"} for c in ORDER_COLUMNS]
    r = await put(append_to=None, columns=read_only)
    assert r.status_code == 200, r.text
    view = r.json()
    assert [m["collection"] for m in view["mappings"]] == ["orders", "customers"]
    assert [m["read_only"] for m in view["mappings"]] == [True, True]
    status = (await client.get(url, headers=bearer(owner))).json()
    assert status["link"]["mappings"][0]["tabs"] == [
        {"sheet_id": None, "title": OCT},
        {"sheet_id": None, "title": NOV},
    ]


# ---------------------------------------------------------------- the sync


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_one_sync_of_the_file_covers_every_collection_in_one_read_and_one_write(
    client, session, fake_google, fake_broker, tmp_path
):
    owner, url, view = await _linked_shop(client, session, fake_google, tmp_path)
    # Known to the app: A-1 (its status changed in the app), a local customer
    # and an order the sheet does not have yet.
    a1 = fake_broker.put("orders", number="A-1", customer_code="ACME", status="paid", total=120)
    fresh = fake_broker.put("orders", number="C-9", customer_code="BOLT", status="new")
    fake_broker.put("customers", code="LOCAL", name="Only in the app")
    reads = fake_google.reads

    r = await client.post(f"{url}/preview", headers=bearer(owner))
    assert r.status_code == 201, r.text
    op = r.json()
    # Headers of every linked tab, then their linked columns: two reads, and
    # the report tab is never read.
    assert fake_google.reads - reads == 2
    created = {(c["collection"], c["tab"], c["row"]): c["data"] for c in op["creates"]}
    assert created == {
        ("orders", NOV, 2): {
            "number": "B-1",
            "customer_code": "ACME",
            "status": "new",
            "total": 50,
            "month": NOV,
        },
        ("orders", OCT, 3): {
            "number": "A-2",
            "customer_code": "BOLT",
            "status": "new",
            "total": 80,
            "month": OCT,
        },
        ("customers", "Customers", 2): {"code": "ACME", "name": "Acme Ltd"},
        ("customers", "Customers", 3): {"code": "BOLT", "name": "Bolt sp. z o.o."},
    }
    (update,) = op["updates"]
    assert (update["collection"], update["tab"], update["row"]) == ("orders", OCT, 2)
    assert update["record_id"] == a1 and update["import"] == {"month": OCT}
    # Both changed status without a base: a person decides.
    assert update["conflicts"] == [
        {"field": "status", "base": None, "app": "paid", "sheet": "sent"}
    ]
    (append,) = op["appends"]
    assert append["record_id"] == fresh and append["tab"] == NOV
    # The local customer stays local: the app only reads that list.
    assert all(a["collection"] == "orders" for a in op["appends"])
    assert set(op["headers"]) == {"orders", "customers"}

    calls = len(fake_broker.calls)
    r = await client.post(
        f"{url}/operations/{op['id']}/apply",
        json={"decisions": {f"{a1}:status": "app"}},
        headers=bearer(owner),
    )
    assert r.status_code == 200, r.text
    assert r.json()["google_status"] == "confirmed"
    # One broker transaction for both collections, one write for both tabs.
    (apply_call,) = [c for c in fake_broker.calls[calls:] if c[0].endswith("/sheets/apply")]
    assert {c["collection"] for c in apply_call[1]["changes"]} == {"orders", "customers"}
    assert len(fake_google.writes) == 1
    assert fake_google.cell(2, 2, OCT) == "paid"
    # The new order went to November, without a value under the computed total.
    assert fake_google.rows(NOV)[-1] == ["C-9", "BOLT", "new"]
    assert fake_google.rows("Customers") == [["ACME", "Acme Ltd"], ["BOLT", "Bolt sp. z o.o."]]
    assert fake_google.rows("Summary") == [["Oct"]]
    assert {r["number"] for r in fake_broker.data["orders"].values()} == {
        "A-1",
        "A-2",
        "B-1",
        "C-9",
    }

    # The tabs are pinned by id: a renamed tab stays linked and its records
    # take the new name.
    mapping = await session.get(SheetMapping, uuid.UUID(view["mappings"][0]["id"]))
    assert mapping is not None
    await session.refresh(mapping)
    assert [t["sheet_id"] for t in mapping.tabs] == [fake_google.ids[OCT], fake_google.ids[NOV]]
    fake_google.rename(OCT, "October")
    # A row moved by hand from October to November is the same record.
    moved = fake_google.grids["October"].pop(2)
    fake_google.grids[NOV].append(moved)
    # The sheet computed the total of the new order meanwhile.
    fake_google.set(3, 3, 99, NOV)
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    assert op["creates"] == [] and op["appends"] == [] and op["issues"] == []
    changes = {
        fake_broker.data["orders"][u["record_id"]]["number"]: u["import"] for u in op["updates"]
    }
    assert changes == {
        "A-1": {"month": "October"},
        "A-2": {"month": NOV},
        "C-9": {"total": 99, "month": NOV},
    }
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.json()["google_status"] == "confirmed"
    status = (await client.get(url, headers=bearer(owner))).json()
    assert status["link"]["mappings"][0]["tabs"][0]["title"] == "October"
    nothing = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    assert not any(nothing["summary"].get(k) for k in ("imports", "exports", "creates", "appends"))


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_a_refusal_in_one_collection_applies_nothing_anywhere(
    client, session, fake_google, fake_broker, tmp_path
):
    owner, url, _ = await _linked_shop(client, session, fake_google, tmp_path)
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    fake_broker.refuse = "customers"
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.status_code == 403
    assert fake_broker.data.get("orders", {}) == {} and fake_google.writes == []


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_a_missing_tab_or_header_stops_the_whole_file(
    client, session, fake_google, fake_broker, tmp_path
):
    owner, url, _ = await _linked_shop(client, session, fake_google, tmp_path)
    fake_google.grids[NOV][0] = ["Number", "Customer", "Total"]
    r = await client.post(f"{url}/preview", headers=bearer(owner))
    assert r.status_code == 409 and r.json()["code"] == "sheet_headers_missing"
    assert r.json()["tab"] == NOV
    fake_google.grids[NOV][0] = ORDER_HEADERS
    fake_google.tabs.remove("Customers")
    r = await client.post(f"{url}/preview", headers=bearer(owner))
    assert r.status_code == 404 and r.json()["code"] == "sheet_tab_not_found"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_no_second_sync_appends_while_a_sheet_write_is_unsettled(
    client, session, fake_google, fake_broker, tmp_path, monkeypatch
):
    """The A/B race: a sync whose app part committed but whose sheet write
    did not happen yet (a crash, a slow Google) must not let another sync
    plan the same append."""
    owner, url, _ = await _linked_shop(client, session, fake_google, tmp_path)
    fake_broker.put("orders", number="C-1", customer_code="ACME", status="new")
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()

    async def crash(*args: Any, **kwargs: Any) -> None:
        return None  # the process died before the sheet write

    real = sync_mod.write.write
    monkeypatch.setattr(sync_mod.write, "write", crash)
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.json()["state"] == "applied" and r.json()["google_status"] == "pending"
    monkeypatch.setattr(sync_mod.write, "write", real)

    r = await client.post(f"{url}/preview", headers=bearer(owner))
    assert r.status_code == 409 and r.json()["code"] == "sheet_sync_unsettled"
    # A check within the grace period leaves it pending; later it finds the
    # cells never written, and only then may the next sync plan the append.
    r = await client.post(f"{url}/operations/{op['id']}/check", json={}, headers=bearer(owner))
    assert r.json()["google_status"] == "pending"
    monkeypatch.setattr(write_mod, "PENDING_GRACE", write_mod.PENDING_GRACE * 0)
    r = await client.post(f"{url}/operations/{op['id']}/check", json={}, headers=bearer(owner))
    assert r.json()["google_status"] == "failed"
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    assert [a["tab"] for a in op["appends"]] == [NOV]
    await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert [r[0] for r in fake_google.rows(NOV)].count("C-1") == 1


# ----------------------------------------------------------- inspecting


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_inspect_lists_every_tab_suggests_groups_and_marks_formulas(
    client, session, fake_google
):
    owner = await mk_user(session)
    await session.commit()
    await _connect(client, owner, fake_google)
    _book(fake_google)
    fake_google.set(2, 3, ("=", "=B2*2", 120), OCT)
    r = await client.post(
        "/api/integrations/google/inspect",
        json={"spreadsheet": fake_google.SPREADSHEET, "tab": OCT},
        headers=bearer(owner),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [t["title"] for t in body["tabs"]] == ["Requests", OCT, NOV, "Customers", "Summary"]
    assert body["tabs"][1] == {
        "sheet_id": fake_google.ids[OCT],
        "title": OCT,
        "grid_rows": 20,
        "headers": ORDER_HEADERS,
    }
    assert body["groups"] == [[OCT, NOV]]
    assert body["tab"] == OCT and body["sheet_id"] == fake_google.ids[OCT]
    formulas = {c["header"]: c["formula"] for c in body["columns"]}
    assert formulas == {"Number": False, "Customer": False, "Status": False, "Total": True}
    by_id = await client.post(
        "/api/integrations/google/inspect",
        json={"spreadsheet": fake_google.SPREADSHEET, "tab": fake_google.ids[NOV]},
        headers=bearer(owner),
    )
    assert by_id.json()["tab"] == NOV
