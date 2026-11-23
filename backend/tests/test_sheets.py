"""Google Sheets links of micro-applications (ADR-0031): cell values, the
three-way comparison, connecting Google, configuring a link and the
preview -> apply -> check cycle against an in-memory Google and broker."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest
from sqlalchemy import select, update

from app import secret_box
from app.config import get_settings
from app.jobs import queue
from app.models import (
    AuditLog,
    GoogleGrant,
    MicroAppEnvironment,
    MicroAppStats,
    SheetBase,
    SheetLink,
    SheetOperation,
)
from app.redis_client import get_redis
from app.routes.admin_users import PatchUserIn, patch_user
from app.services.micro_applications import document
from app.services.micro_applications.runtime import BROKER_HEARTBEAT_KEY
from app.services.notifications import inbox
from app.services.sheets import auto, common, google, inspect, values, write
from app.services.sheets.compare import UNCONFIRMED, Sheet, compare
from app.util import now as utc_now
from tests.conftest import mk_user
from tests.test_microapps import _enabled, apps_db, bearer, needs_pg  # noqa: F401 (fixtures)
from tests.test_microapps_api import SVC, _published

# ---------------------------------------------------------------- values

STRING = {"type": "string", "maxLength": 20}
INT = {"type": "integer"}
DEC = {"type": "decimal", "precision": 10, "scale": 2}
DATE = {"type": "date"}
TS = {"type": "timestamptz"}
BOOL = {"type": "boolean"}
ENUM = {"type": "enum", "values": ["new", "done"]}


def test_cells_become_field_values_whatever_the_sheet_shows():
    assert values.from_cell(STRING, 12.0) == "12"
    assert values.from_cell(STRING, "  ") is None
    assert values.from_cell(INT, 7.0) == 7
    assert values.from_cell(INT, "7") == 7
    assert values.from_cell(DEC, 12.5) == "12.50"
    assert values.from_cell(DEC, "12,5") == "12.50"
    assert values.from_cell(DATE, 46348) == "2026-11-22"
    assert values.from_cell(DATE, "22.11.2026") == "2026-11-22"
    assert values.from_cell(DATE, "2026-11-22") == "2026-11-22"
    assert values.from_cell(TS, "2026-11-22T10:00:00+01:00") == "2026-11-22T09:00:00.000Z"
    assert values.from_cell(TS, 46348.5, tz="Europe/Warsaw") == "2026-11-22T11:00:00.000Z"
    assert values.from_cell(BOOL, "tak") is True and values.from_cell(BOOL, False) is False
    assert values.from_cell(ENUM, "done") == "done"
    for field, bad in (
        (INT, 1.5),
        (DATE, "soon"),
        (ENUM, "maybe"),
        (BOOL, "perhaps"),
        (STRING, "x" * 21),
        (TS, "22.11.2026 o 10"),
    ):
        with pytest.raises(values.CellError):
            values.from_cell(field, bad)


def test_app_values_meet_cell_values_in_one_form():
    assert values.from_app(DEC, "12.5") == values.from_cell(DEC, 12.5)
    assert values.from_app(TS, "2026-11-22T09:00:00Z") == "2026-11-22T09:00:00.000Z"
    assert values.from_app(STRING, "") is None


def test_written_cells_are_typed_and_never_formulas():
    assert values.to_cell(STRING, '=IMPORTXML("http://x")') == {
        "userEnteredValue": {"stringValue": '=IMPORTXML("http://x")'}
    }
    assert values.to_cell(INT, 3) == {"userEnteredValue": {"numberValue": 3}}
    assert values.to_cell(DEC, "0.10") == {"userEnteredValue": {"numberValue": 0.1}}
    assert values.to_cell(DEC, "12345678901234567.89")["userEnteredValue"] == {
        "stringValue": "12345678901234567.89"
    }
    assert values.to_cell(DATE, "2026-11-22")["userEnteredValue"] == {"numberValue": 46348}
    assert values.to_cell(BOOL, True) == {"userEnteredValue": {"boolValue": True}}
    assert values.to_cell(STRING, None) == {}


# ------------------------------------------------------------ comparison

FIELDS = {"title": STRING, "note": STRING, "status": ENUM}
ID1, ID2, ID3 = (str(uuid.UUID(int=i)) for i in (1, 2, 3))


def _link(key_field: str | None = None, **owners: str) -> SheetLink:
    cols = {"title": "both", "note": "sheet", "status": "app", **owners}
    return SheetLink(
        key_field=key_field,
        columns=[{"field": f, "header": f.capitalize(), "owner": o} for f, o in cols.items()],
        account_mode="owner_account",
        revision=1,
    )


def _sheet(*rows: list[Any]) -> Sheet:
    header = ["Title", "Note", "Status"]
    return Sheet(
        sheet_id=0,
        title="Data",
        tz="UTC",
        row_count=100,
        header={h.casefold(): i for i, h in enumerate(header)},
        rows=[list(r) for r in rows],
    )


def _app(
    rid: str, title: str, note: str | None = None, status: str = "new", revision: int = 1
) -> dict:
    return {"id": rid, "revision": revision, "title": title, "note": note, "status": status}


def test_each_owner_flows_one_way_and_both_takes_the_side_that_changed():
    sheet = _sheet(["Sheet title", "typed in sheet", "new"])
    base = {ID1: {"title": "Old", "note": None, "status": "new"}}
    # The app kept the old title: the sheet's edit wins; status is the app's.
    # The row matches by the row it was last seen in, one value still equal.
    plan = compare(_link(), FIELDS, sheet, [_app(ID1, "Old", status="done")], base, {ID1: 2})
    (u,) = plan["updates"]
    assert u["import"] == {"title": "Sheet title", "note": "typed in sheet"}
    assert u["export"] == {"status": "done"} and u["conflicts"] == []
    # The app changed the title, the sheet did not: export.
    sheet = _sheet(["Old", None, "done"])
    plan = compare(_link(), FIELDS, sheet, [_app(ID1, "App title", status="done")], base)
    assert plan["updates"][0]["export"] == {"title": "App title"}


def test_both_sides_changing_one_cell_is_a_conflict_not_a_clock_race():
    sheet = _sheet(["Sheet title", None, "new"])
    base = {ID1: {"title": "Old", "note": None, "status": "new"}}
    plan = compare(_link(), FIELDS, sheet, [_app(ID1, "App title")], base)
    assert plan["updates"][0]["conflicts"] == [
        {"field": "title", "base": "Old", "app": "App title", "sheet": "Sheet title"}
    ]


def test_new_rows_create_records_and_records_without_rows_are_appended():
    sheet = _sheet(["From the sheet", "n", "done"], [None, None, None], ["Kept", None, "new"])
    plan = compare(
        _link(),
        FIELDS,
        sheet,
        [_app(ID1, "Kept"), _app(ID2, "Only in the app")],
        {},
        required=["title"],
        new_id=lambda: ID3,
    )
    # The status column is the app's: a new row cannot set it.
    assert plan["creates"] == [
        {"row": 2, "record_id": ID3, "data": {"title": "From the sheet", "note": "n"}}
    ]
    assert plan["appends"] == [
        {"record_id": ID2, "values": {"title": "Only in the app", "note": None, "status": "new"}}
    ]
    # A row equal to an app record never synced is that record, not a new one.
    assert plan["converged"] == [
        {"record_id": ID1, "values": {"title": "Kept", "note": None, "status": "new"}}
    ]
    assert plan["rows"] == {ID1: 4}
    assert set(plan["snapshot"]) == {"2"}


def test_rows_are_found_wherever_they_moved_and_edited_ones_where_they_were():
    base = {
        ID1: {"title": "A", "note": "a", "status": "new"},
        ID2: {"title": "B", "note": "b", "status": "new"},
        ID3: {"title": "C", "note": "c", "status": "new"},
    }
    app = [_app(ID1, "A", "a"), _app(ID2, "B", "b"), _app(ID3, "C", "c")]
    seen = {ID1: 2, ID2: 3, ID3: 4}
    # Sorted backwards, a row inserted on top and B's note edited.
    sheet = _sheet(["New", None, None], ["C", "c", "new"], ["B", "b2", "new"], ["A", "a", "new"])
    plan = compare(_link(), FIELDS, sheet, app, base, seen, new_id=lambda: "n")
    assert plan["rows"] == {ID3: 3, ID2: 4, ID1: 5}
    assert [(u["record_id"], u["import"]) for u in plan["updates"]] == [(ID2, {"note": "b2"})]
    assert [c["row"] for c in plan["creates"]] == [2] and plan["issues"] == []
    # Records found where they were last seen are left out: the base keeps
    # their rows, so an apply rewrites no base row for them.
    sheet = _sheet(["A", "a", "new"], ["B", "b2", "new"], ["C", "c", "new"])
    plan = compare(_link(), FIELDS, sheet, app, base, seen, new_id=lambda: "n")
    assert plan["rows"] == {}
    assert [(u["record_id"], u["import"]) for u in plan["updates"]] == [(ID2, {"note": "b2"})]


def test_a_key_field_matches_rows_by_its_value():
    base = {ID1: {"title": "T-1", "note": "x", "status": "new"}}
    app = [_app(ID1, "T-1", "x"), _app(ID2, "T-2")]
    sheet = _sheet(["T-2", "all changed", "done"], ["T-1", "y", "new"], ["T-2", "", ""])
    plan = compare(_link(key_field="title"), FIELDS, sheet, app, base)
    assert plan["rows"] == {ID2: 2, ID1: 3}
    assert plan["issues"] == [{"kind": "duplicate_key", "row": 4, "first_row": 2}]
    # A key no record has yet: a new record, as on the first sync of a sheet.
    sheet.rows.append(["T-3", None, None])
    plan = compare(_link(key_field="title"), FIELDS, sheet, app, base, new_id=lambda: ID3)
    assert plan["creates"] == [{"row": 5, "record_id": ID3, "data": {"title": "T-3"}}]


def test_rows_that_cannot_be_trusted_are_reported_and_left_alone():
    sheet = _sheet(
        ["Gone", None, "new"],
        [None, "a note but no title", None],
        ["B", None, "bogus"],
    )
    base = {ID3: {"title": "Gone", "note": None, "status": "new"}, ID2: {"title": "B"}}
    app = [_app(ID2, "B", status="new")]
    plan = compare(_link(status="both"), FIELDS, sheet, app, base, required=["title"])
    kinds = sorted(i["kind"] for i in plan["issues"])
    # A row of a record deleted in the app is not created again.
    assert kinds == ["invalid_value", "missing_required", "record_not_in_app"]
    assert plan["creates"] == [] and plan["appends"] == []
    # Only the app's own column filled: nothing a record can be made of.
    plan = compare(_link(), FIELDS, _sheet([None, None, "done"]), [], {})
    assert plan["issues"] == [{"kind": "unmatched_row", "row": 2}]
    # A record whose row was deleted is not deleted in the app, nor re-added.
    plan = compare(_link(), FIELDS, _sheet(), [_app(ID2, "B")], base)
    assert (
        plan["issues"] == [{"kind": "removed_from_sheet", "record_id": ID2}]
        and plan["appends"] == []
    )


def test_an_append_not_confirmed_is_appended_again():
    base = {ID1: {"title": "A", "note": None, "status": "new", UNCONFIRMED: True}}
    plan = compare(_link(), FIELDS, _sheet(), [_app(ID1, "A")], base)
    assert [a["record_id"] for a in plan["appends"]] == [ID1] and plan["issues"] == []
    # It did land: the row is that record, and the flag goes.
    plan = compare(_link(), FIELDS, _sheet(["A", None, "new"]), [_app(ID1, "A")], base)
    assert plan["converged"] == [{"record_id": ID1, "values": {UNCONFIRMED: False}}]


def test_a_record_the_app_rule_locks_does_not_take_sheet_values():
    sheet = _sheet(["Renamed", None, "new"])
    base = {ID1: {"title": "A", "note": None, "status": "done"}}
    plan = compare(
        _link(),
        FIELDS,
        sheet,
        [_app(ID1, "A", status="done")],
        base,
        {ID1: 2},
        conditions={"status": "new"},
    )
    assert plan["issues"] == [
        {"kind": "not_editable", "row": 2, "record_id": ID1, "fields": ["title"]}
    ]
    # The app's own column still flows to the sheet.
    assert plan["updates"][0]["export"] == {"status": "done"} and plan["updates"][0]["import"] == {}


def test_a_missing_header_stops_the_comparison():
    sheet = _sheet()
    sheet.header.pop("note")
    with pytest.raises(Exception) as e:
        compare(_link(), FIELDS, sheet, [], {})
    assert getattr(e.value, "code", "") == "sheet_headers_missing"


# --------------------------------------------------------- fake Google


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


class FakeGoogle:
    """One spreadsheet in memory, served like the Sheets API."""

    def __init__(self) -> None:
        self.SPREADSHEET = "1Sheet" + uuid.uuid4().hex
        self.grid: list[list[Any]] = []
        self.row_count = 20
        self.tabs = ["Requests"]
        self.fail_write: str | None = None
        self.deny = False
        self.writes: list[list[dict]] = []
        self.reads = 0
        self.sub = "google-sub-1"
        self.scope = google.SCOPES

    def cell(self, row: int, col: int) -> Any:
        r = self.grid[row - 1] if row - 1 < len(self.grid) else []
        return r[col] if col < len(r) else None

    def set(self, row: int, col: int, value: Any) -> None:
        while len(self.grid) < row:
            self.grid.append([])
        r = self.grid[row - 1]
        while len(r) <= col:
            r.append(None)
        r[col] = value

    def _values(self) -> list[list[Any]]:
        rows = [[v for v in r] for r in self.grid]
        for r in rows:
            while r and r[-1] in (None, ""):
                r.pop()
        while rows and not rows[-1]:
            rows.pop()
        return rows

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(google.TOKEN_URL):
            form = parse_qs(request.content.decode())
            body = {
                "access_token": f"at-{uuid.uuid4().hex[:6]}",
                "expires_in": 3599,
                "scope": self.scope,
            }
            if form["grant_type"] == ["authorization_code"]:
                body["refresh_token"] = "rt-secret-1"
            return httpx.Response(200, json=body)
        if url.startswith(google.USERINFO_URL):
            return httpx.Response(
                200, json={"sub": self.sub, "email": "me@grupa.test", "email_verified": True}
            )
        if url.startswith(google.REVOKE_URL):
            return httpx.Response(200)
        if self.deny:
            return httpx.Response(403, json={"error": {"code": 403, "message": "denied"}})
        path = unquote(urlsplit(url).path)
        if path.endswith(":batchUpdate"):
            if self.fail_write == "timeout":
                raise httpx.ReadTimeout("lost", request=request)
            if self.fail_write == "timeout_after_apply":
                self._apply(json.loads(request.content)["requests"])
                raise httpx.ReadTimeout("lost", request=request)
            self._apply(json.loads(request.content)["requests"])
            return httpx.Response(200, json={"replies": []})
        if path.endswith("/values:batchGet"):
            self.reads += 1
            grid = self._values()
            out = []
            for rng in request.url.params.get_list("ranges"):
                col = _col_index(rng.split("!")[1].split(":")[0].rstrip("0123456789"))
                out.append({"values": [[r[col] if col < len(r) else None for r in grid[1:]]]})
            for vr in out:
                column = vr["values"][0]
                while column and column[-1] in (None, ""):
                    column.pop()
            return httpx.Response(200, json={"valueRanges": out})
        if "/values/" in path:
            return httpx.Response(200, json={"values": self._values()[:1]})
        if request.url.params.get("includeGridData") == "true":
            return httpx.Response(200, json=self._grid_data())
        return httpx.Response(
            200,
            json={
                "properties": {"title": "Book", "timeZone": "Europe/Warsaw"},
                "sheets": [
                    {
                        "properties": {
                            "sheetId": i,
                            "title": t,
                            "gridProperties": {"rowCount": self.row_count, "columnCount": 10},
                        }
                    }
                    for i, t in enumerate(self.tabs)
                ],
            },
        )

    def _grid_data(self) -> dict:
        def cell(value: Any) -> dict:
            if value is None:
                return {}
            if isinstance(value, tuple):  # ("DATE", serial)
                return {
                    "effectiveValue": {"numberValue": value[1]},
                    "effectiveFormat": {"numberFormat": {"type": value[0]}},
                    "formattedValue": str(value[1]),
                }
            key = (
                "boolValue"
                if isinstance(value, bool)
                else "numberValue"
                if isinstance(value, int | float)
                else "stringValue"
            )
            return {"effectiveValue": {key: value}, "formattedValue": str(value)}

        rows = [{"values": [cell(v) for v in r]} for r in self.grid]
        return {
            "properties": {"title": "Book", "timeZone": "Europe/Warsaw"},
            "sheets": [{"properties": {"title": self.tabs[0]}, "data": [{"rowData": rows}]}],
        }

    def _apply(self, requests: list[dict]) -> None:
        self.writes.append(requests)
        for req in requests:
            if "appendDimension" in req:
                self.row_count += req["appendDimension"]["length"]
                continue
            rng = req["updateCells"]["range"]
            assert rng["endRowIndex"] <= self.row_count, "write beyond the grid"
            cells = req["updateCells"]["rows"][0]["values"]
            assert len(cells) == rng["endColumnIndex"] - rng["startColumnIndex"]
            for i, cell in enumerate(cells):
                value = next(iter(cell.get("userEnteredValue", {}).values()), None)
                self.set(rng["startRowIndex"] + 1, rng["startColumnIndex"] + i, value)


class FakeBroker:
    """The linked collection of the `requests` example, as the broker serves it."""

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.applied: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []
        self.down = False
        self.lose_answer = False

    def add(
        self, title: str, description: str = "", status: str = "submitted", rid: str | None = None
    ) -> str:
        rid = rid or str(uuid.uuid4())
        self.rows[rid] = {
            "id": rid,
            "revision": 1,
            "title": title,
            "description": description,
            "status": status,
        }
        return rid

    async def __call__(self, settings, method, path, body=None, timeout=15.0):
        self.calls.append((path, body))
        if self.down:
            raise httpx.ConnectError("broker down")
        if path.endswith("/sheets/stamp"):
            revisions = sum(r["revision"] for r in self.rows.values())
            return {"release": "r1", "stamp": f"r1:{len(self.rows)}:{revisions}"}
        if path.endswith("/sheets/read"):
            return {
                "release": "r1",
                "truncated": False,
                "rows": [dict(r) for r in self.rows.values()],
            }
        if body["key"] in self.applied:
            return {**self.applied[body["key"]], "replayed": True}
        results = []
        for c in body["changes"]:
            if c["op"] == "update":
                row = self.rows[c["id"]]
                if row["revision"] != c["revision"]:
                    request = httpx.Request("POST", "http://broker")
                    resp = httpx.Response(
                        412, json={"code": "revision_mismatch", "change": 0}, request=request
                    )
                    raise httpx.HTTPStatusError("412", request=request, response=resp)
                row.update(c["patch"])
                row["revision"] += 1
                results.append({"id": row["id"], "revision": row["revision"]})
            else:
                rid = self.add(c["data"]["title"], c["data"].get("description", ""), rid=c["id"])
                values = {f: v for f, v in self.rows[rid].items() if f in body.get("fields", [])}
                results.append({"id": rid, "revision": 1, "values": values})
        out = {"release": "r1", "results": results}
        self.applied[body["key"]] = out
        if self.lose_answer:
            self.lose_answer = False
            raise httpx.ReadTimeout("committed, answer lost")
        return {**out, "replayed": False}


@pytest.fixture
def fake_google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(google, "transport", httpx.MockTransport(fake.handler))
    s = get_settings()
    monkeypatch.setattr(s, "google_sheets_client_id", "client-id.apps.googleusercontent.com")
    monkeypatch.setattr(s, "google_sheets_client_secret", "client-secret")
    return fake


@pytest.fixture
def fake_broker(monkeypatch):
    fake = FakeBroker()
    monkeypatch.setattr(common, "broker_admin", fake)
    return fake


async def _connect(client, user, fake: FakeGoogle) -> None:
    r = await client.get("/api/integrations/google/connect?next=/a/b", headers=bearer(user))
    assert r.status_code == 302, r.text
    target = urlsplit(r.headers["location"])
    params = parse_qs(target.query)
    assert target.netloc == "accounts.google.com" and params["code_challenge_method"] == ["S256"]
    assert google.SHEETS_SCOPE in params["scope"][0] and params["login_hint"] == [user.email]
    state = params["state"][0]
    r = await client.get(
        f"/api/integrations/google/callback?state={state}&code=c-1", headers=bearer(user)
    )
    assert r.status_code == 302 and r.headers["location"] == "/a/b?google=connected", r.headers


COLUMNS = [
    {"field": "title", "header": "Title", "owner": "both"},
    {"field": "description", "header": "Description", "owner": "sheet"},
    {"field": "status", "header": "Status", "owner": "app"},
]


async def _linked(client, session, fake: FakeGoogle, mode: str = "owner_account", **extra: Any):
    owner = await mk_user(session)
    await session.commit()
    op, _ = await _published(client, session, owner)
    asset_id = op["asset_id"]
    await _connect(client, owner, fake)
    r = await client.put(
        f"/api/micro-applications/{asset_id}/sheets",
        json={
            "collection": "requests",
            "spreadsheet": f"https://docs.google.com/spreadsheets/d/{fake.SPREADSHEET}/edit#gid=0",
            "sheet_title": "Requests",
            "columns": COLUMNS,
            "account_mode": mode,
            **extra,
        },
        headers=bearer(owner),
    )
    assert r.status_code == 200, r.text
    for col, header in enumerate(["Title", "Description", "Status"]):
        fake.set(1, col, header)
    return owner, asset_id


# ----------------------------------------------------------- connecting


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_connecting_stores_an_encrypted_grant_bound_to_the_ics_user(
    client, session, fake_google
):
    alice = await mk_user(session)
    bob = await mk_user(session)
    await session.commit()
    await _connect(client, alice, fake_google)
    grant = await session.scalar(select(GoogleGrant).where(GoogleGrant.user_id == alice.id))
    assert grant.subject == "google-sub-1" and "rt-secret-1" not in grant.refresh_token_enc
    assert (
        secret_box.decrypt(get_settings(), "google-grant", grant.refresh_token_enc) == "rt-secret-1"
    )
    me = (await client.get("/api/integrations/google", headers=bearer(alice))).json()
    assert me == {"enabled": True, "connected": True, "email": "me@grupa.test"}

    # A callback carrying someone else's state never attaches their account.
    r = await client.get(
        "/api/integrations/google/connect?next=/v/x?tab=sheets", headers=bearer(alice)
    )
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = await client.get(
        f"/api/integrations/google/callback?state={state}&code=c", headers=bearer(bob)
    )
    assert r.headers["location"] == "/v/x?tab=sheets&google=google_state_mismatch"
    assert await session.scalar(select(GoogleGrant).where(GoogleGrant.user_id == bob.id)) is None

    # Sheets left unticked on the consent screen: nothing is stored.
    fake_google.scope = "openid email"
    r = await client.get("/api/integrations/google/connect", headers=bearer(bob))
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    r = await client.get(
        f"/api/integrations/google/callback?state={state}&code=c", headers=bearer(bob)
    )
    assert r.headers["location"] == "/?google=google_scope_missing"
    r = await client.get(
        "/api/integrations/google/callback?state=gone&error=access_denied", headers=bearer(bob)
    )
    assert r.headers["location"] == "/?google=declined"

    assert (await client.delete("/api/integrations/google", headers=bearer(alice))).json() == {
        "disconnected": True
    }
    alice_id = alice.id
    session.expire_all()
    assert await session.scalar(select(GoogleGrant).where(GoogleGrant.user_id == alice_id)) is None


# --------------------------------------------------------------- the link


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_link_rules(client, session, fake_google):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    body = {
        "collection": "requests",
        "spreadsheet": fake_google.SPREADSHEET,
        "sheet_title": "Requests",
        "account_mode": "per_user",
    }

    async def put(columns, who=owner, **extra):
        return await client.put(
            url, json={**body, "columns": columns, **extra}, headers=bearer(who)
        )

    assert (await client.get(url, headers=bearer(owner))).json()["row_limit"] == 5000
    # status cannot change through the update rule: only the app may own it.
    r = await put([{"field": "status", "header": "Status", "owner": "both"}])
    assert r.status_code == 400 and r.json()["code"] == "field_not_writable"
    r = await put([{"field": "nope", "header": "X", "owner": "app"}])
    assert r.json()["code"] == "field_not_found"
    r = await put(
        [
            {"field": "title", "header": "Name", "owner": "both"},
            {"field": "description", "header": "name ", "owner": "sheet"},
        ]
    )
    assert r.json()["code"] == "column_duplicate"
    r = await put(COLUMNS[:1], key_field="description")
    assert r.json()["code"] == "key_field_invalid"
    r = await put(COLUMNS, expected_revision=99)
    assert r.status_code == 409 and r.json()["code"] == "sheet_link_changed"
    r = await put(COLUMNS, expected_revision=1)
    assert r.status_code == 200 and r.json()["revision"] == 2

    # Another app cannot write to the same spreadsheet.
    other_owner = await mk_user(session)
    await session.commit()
    op, _ = await _published(client, session, other_owner)
    r = await client.put(
        f"/api/micro-applications/{op['asset_id']}/sheets",
        json={**body, "columns": COLUMNS},
        headers=bearer(other_owner),
    )
    assert r.status_code == 409 and r.json()["code"] == "spreadsheet_already_linked"

    # Someone without an owner-like role neither configures nor runs it.
    stranger = await mk_user(session)
    await session.commit()
    assert (await put(COLUMNS, who=stranger)).status_code == 404
    assert (await client.post(f"{url}/preview", headers=bearer(stranger))).status_code == 404


# ------------------------------------------------------------- the sync


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_preview_apply_and_a_second_preview_with_nothing_left(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    both = fake_broker.add("Laptop", "old desc")
    app_only = fake_broker.add("Monitor", "", "approved")
    # The sheet as people keep it: no ids anywhere.
    fake_google.set(2, 0, "Laptop")
    fake_google.set(2, 1, "dock too")
    fake_google.set(2, 2, "submitted")
    fake_google.set(3, 0, "Chair")  # a new row
    fake_google.set(3, 1, "ergonomic")

    r = await client.post(f"{url}/preview", headers=bearer(owner))
    assert r.status_code == 201, r.text
    op = r.json()
    # Most of its values match: the Laptop row is that record.
    (u,) = op["updates"]
    assert u["record_id"] == both and u["import"] == {"description": "dock too"}
    (chair_create,) = op["creates"]
    assert chair_create["row"] == 3
    assert chair_create["data"] == {"title": "Chair", "description": "ergonomic"}
    assert [a["record_id"] for a in op["appends"]] == [app_only]

    apply_url = f"{url}/operations/{op['id']}/apply"
    r = await client.post(apply_url, json={}, headers=bearer(owner))
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["state"] == "applied" and done["google_status"] == "confirmed"

    assert fake_broker.rows[both]["description"] == "dock too"
    assert any(r["title"] == "Chair" for r in fake_broker.rows.values())
    # The app's default status went to the new row; the record got a row of
    # its own; no column was added to the sheet.
    assert fake_google.cell(3, 2) == "submitted"
    assert [fake_google.cell(4, c) for c in range(3)] == ["Monitor", None, "approved"]
    assert fake_google.cell(1, 3) is None
    assert len(fake_google.writes) == 1  # one atomic batchUpdate

    # Applying again is a no-op that reports the same outcome.
    again = await client.post(apply_url, json={}, headers=bearer(owner))
    assert again.json()["state"] == "applied" and len(fake_google.writes) == 1

    # Both sides now agree and the base remembers it: nothing to do.
    nothing = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    assert nothing["summary"] == {
        "imports": 0,
        "exports": 0,
        "conflicts": 0,
        "creates": 0,
        "appends": 0,
        "issues": 0,
        "agreed": 0,
    }
    base = {str(b.record_id): b for b in await session.scalars(select(SheetBase))}
    assert base[both].values["description"] == "dock too" and base[both].row == 2
    assert base[app_only].values["status"] == "approved" and base[app_only].row == 4

    # Someone sorts the sheet and inserts a row on top: nothing changes.
    fake_google.grid.insert(1, ["Phone", None, None])
    fake_google.grid[2:] = list(reversed(fake_google.grid[2:]))
    moved = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    assert moved["summary"]["creates"] == 1 and moved["summary"]["issues"] == 0
    assert moved["updates"] == [] and moved["appends"] == []

    # Both sides rename the same record: a conflict a person decides.
    laptop_row = next(i for i, r in enumerate(fake_google.grid, 1) if r and r[0] == "Laptop")
    fake_google.set(laptop_row, 0, "Laptop 14")
    fake_broker.rows[both]["title"] = "Laptop 15"
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    (u,) = op["updates"]
    assert u["conflicts"] == [
        {"field": "title", "base": "Laptop", "app": "Laptop 15", "sheet": "Laptop 14"}
    ]
    apply_url = f"{url}/operations/{op['id']}/apply"
    r = await client.post(apply_url, json={}, headers=bearer(owner))
    assert r.status_code == 400 and r.json()["code"] == "decisions_missing"
    r = await client.post(
        apply_url, json={"decisions": {f"{both}:title": "sheet"}}, headers=bearer(owner)
    )
    assert r.status_code == 200, r.text
    assert fake_broker.rows[both]["title"] == "Laptop 14"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_a_sheet_edited_after_the_preview_is_not_overwritten(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    fake_broker.add("Desk")
    fake_google.set(2, 0, "Desk")
    fake_google.set(2, 2, "approved")  # the app's column differs: export planned
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    fake_google.set(2, 0, "Desk XL")  # someone types meanwhile
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.status_code == 409 and r.json()["code"] == "sheet_changed"
    assert fake_google.writes == [] and fake_broker.calls[-1][0].endswith("/sheets/read")
    stale = (await client.get(f"{url}/operations/{op['id']}", headers=bearer(owner))).json()
    assert stale["state"] == "stale"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_a_lost_google_answer_is_uncertain_until_read_back(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    fake_broker.add("Phone", status="approved")
    fake_google.set(2, 0, "Phone")
    fake_google.set(2, 2, "submitted")

    async def round_(mode):
        fake_google.fail_write = mode
        op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
        r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
        assert r.status_code == 200 and r.json()["google_status"] == "uncertain", r.text
        fake_google.fail_write = None
        return op["id"]

    # The write never landed: the check says so and the next preview offers it again.
    op_id = await round_("timeout")
    writes = len(fake_google.writes)
    r = await client.post(f"{url}/operations/{op_id}/check", headers=bearer(owner))
    assert r.json()["google_status"] == "failed" and r.json()["error"] == "google_not_applied"
    assert len(fake_google.writes) == writes  # a check never writes

    # A crash right before the write leaves it pending: the same check settles it.
    saved = await session.scalar(
        select(SheetOperation).where(SheetOperation.id == uuid.UUID(op_id))
    )
    saved.google_status = "pending"
    await session.commit()
    # A fresh `pending` may still be on its way: the check waits.
    r = await client.post(f"{url}/operations/{op_id}/check", headers=bearer(owner))
    assert r.json()["google_status"] == "pending"
    saved.updated_at = saved.updated_at - write.PENDING_GRACE * 2
    await session.commit()
    r = await client.post(f"{url}/operations/{op_id}/check", headers=bearer(owner))
    assert r.json()["google_status"] == "failed"

    # It landed but the answer was lost: the check confirms it.
    op_id = await round_("timeout_after_apply")
    r = await client.post(f"{url}/operations/{op_id}/check", headers=bearer(owner))
    assert r.json()["google_status"] == "confirmed"
    assert fake_google.cell(2, 2) == "approved"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_an_interrupted_apply_resumes_without_a_second_write(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    fake_google.set(2, 0, "New from sheet")
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    # The broker commits, then its answer is lost.
    fake_broker.lose_answer = True
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.status_code == 503 and r.json()["code"] == "broker_unavailable"
    saved = await session.scalar(
        select(SheetOperation).where(SheetOperation.id == uuid.UUID(op["id"]))
    )
    assert saved.state == "applying" and fake_google.writes == []
    # The same request resumes with the same key: replayed, not repeated.
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.status_code == 200 and r.json()["state"] == "applied"
    assert sum(1 for p, _ in fake_broker.calls if p.endswith("/sheets/apply")) == 2
    assert sum(1 for r in fake_broker.rows.values() if r["title"] == "New from sheet") == 1
    assert len(fake_google.writes) == 1


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_a_record_changed_in_the_app_after_the_preview_makes_it_stale(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    rid = fake_broker.add("Mouse", "a")
    fake_google.set(2, 0, "Mouse")
    fake_google.set(2, 1, "b")
    fake_google.set(2, 2, "submitted")
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    fake_broker.rows[rid]["revision"] = 7
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.status_code == 409 and r.json()["code"] == "app_changed"
    assert fake_google.writes == []


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_per_user_uses_only_the_callers_account_and_asks_the_owner_for_access(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google, mode="per_user")
    url = f"/api/micro-applications/{asset_id}/sheets"
    colleague = await mk_user(session)
    await session.commit()
    await client.put(
        f"/api/micro-applications/{asset_id}/access",
        json={
            "user_email": colleague.email,
            "permissions": ["app.control", "requests.read"],
            "can_open": True,
        },
        headers=bearer(owner),
    )
    r = await client.post(f"{url}/preview", headers=bearer(colleague))
    # The owner's grant is never a fallback for someone else.
    assert r.status_code == 409 and r.json()["code"] == "google_not_connected"
    assert r.json()["action"] == "connect_google"

    fake_google.sub = "google-sub-2"
    await _connect(client, colleague, fake_google)
    fake_google.deny = True
    r = await client.post(f"{url}/preview", headers=bearer(colleague))
    assert (
        r.status_code == 409
        and r.json()["code"] == "google_no_access"
        and r.json()["action"] == "request_access"
    )
    r = await client.post(f"{url}/request-access", headers=bearer(colleague))
    assert r.json() == {"sent": True}
    assert (await client.post(f"{url}/request-access", headers=bearer(colleague))).json() == {
        "sent": False,
        "reason": "already_requested",
    }
    entries, _ = await inbox.page(get_redis(), owner.id, before=None, limit=10, unread_only=False)
    (entry,) = entries
    assert entry.payload["c"] == "sheets.access_requested"
    assert entry.payload["sl"] and entry.payload["x"]["email"] == "me@grupa.test"


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_owner_account_is_lent_only_by_the_owner_and_a_new_account_voids_previews(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    fake_google.set(2, 0, "Row")
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    # Reconnecting another Google account changes whose account writes.
    fake_google.sub = "another-account"
    await _connect(client, owner, fake_google)
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.status_code == 409 and r.json()["code"] == "sheet_link_changed"


# ------------------------------------------------- findings of the review


def test_ambiguous_cells_are_refused_not_guessed():
    for bad in ("1,000", "1.234,5", "-12,345,678"):
        with pytest.raises(values.CellError):
            values.from_cell(DEC, bad)
    assert values.from_cell(DEC, "12,5") == "12.50"
    with pytest.raises(values.CellError):
        values.from_cell(DATE, "03/04/2026")  # month or day first?
    # Beyond 2^53 the broker sends integers as text.
    assert values.from_app(INT, "9007199254740993") == values.from_cell(INT, "9007199254740993")


def test_a_doubled_linked_header_stops_the_comparison():
    sheet = _sheet()
    sheet.duplicates.add("title")
    with pytest.raises(Exception) as e:
        compare(_link(), FIELDS, sheet, [], {})
    assert getattr(e.value, "code", "") == "sheet_headers_duplicate"


def test_writes_go_in_runs_of_adjacent_cells():
    sheet = _sheet()
    fields = {"title": STRING, "note": STRING, "due": DATE}
    cells = [
        {"row": 5, "col": 1, "field": "note", "value": None},
        {"row": 5, "col": 0, "field": "title", "value": "A"},
        {"row": 5, "col": 2, "field": "due", "value": "2026-11-22"},
        {"row": 7, "col": 0, "field": "title", "value": "B"},
    ]
    requests = write._requests(cells, fields, sheet)
    ranges = [
        (
            r["updateCells"]["range"]["startRowIndex"],
            r["updateCells"]["range"]["startColumnIndex"],
            r["updateCells"]["range"]["endColumnIndex"],
            r["updateCells"]["fields"],
        )
        for r in requests
    ]
    assert ranges == [
        (4, 0, 2, "userEnteredValue"),
        (4, 2, 3, "userEnteredValue,userEnteredFormat.numberFormat"),
        (6, 0, 1, "userEnteredValue"),
    ]


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_a_failed_sheet_write_after_a_create_does_not_create_twice(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    fake_google.set(2, 0, "Lamp")
    fake_google.set(2, 1, "desk lamp")
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    fake_google.fail_write = "timeout"
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.json()["google_status"] == "uncertain"
    fake_google.fail_write = None
    assert [r["title"] for r in fake_broker.rows.values()] == ["Lamp"]
    lamp = next(iter(fake_broker.rows))

    # The row is recognised by its content as the record already made.
    again = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    assert again["creates"] == []
    assert [u["record_id"] for u in again["updates"]] == [lamp]
    r = await client.post(f"{url}/operations/{again['id']}/apply", json={}, headers=bearer(owner))
    assert r.json()["google_status"] == "confirmed"
    assert fake_google.cell(2, 2) == "submitted" and len(fake_broker.rows) == 1
    done = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    assert done["summary"]["imports"] == 0 and done["summary"]["exports"] == 0


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_another_mapping_forgets_the_agreed_values_it_no_longer_vouches_for(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    rid = fake_broker.add("Pen", "blue")
    for col, value in enumerate(["Pen", "blue", "submitted"]):
        fake_google.set(2, col, value)
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    base = await session.scalar(select(SheetBase).where(SheetBase.record_id == uuid.UUID(rid)))
    assert set(base.values) == {"title", "description", "status"}

    body = {
        "collection": "requests",
        "spreadsheet": fake_google.SPREADSHEET,
        "sheet_title": "Requests",
        "account_mode": "owner_account",
    }
    renamed = [dict(c) for c in COLUMNS]
    renamed[0]["header"] = "Name"
    r = await client.put(url, json={**body, "columns": renamed}, headers=bearer(owner))
    assert r.status_code == 200, r.text
    await session.refresh(base)
    assert set(base.values) == {"description", "status"}

    fake_google.tabs.append("Other")
    r = await client.put(
        url, json={**body, "sheet_title": "Other", "columns": renamed}, headers=bearer(owner)
    )
    assert r.status_code == 200
    session.expire_all()
    assert (
        await session.scalar(select(SheetBase).where(SheetBase.record_id == uuid.UUID(rid))) is None
    )


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_the_link_waits_for_an_applying_sync_and_only_its_author_checks_with_their_account(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google, mode="per_user")
    url = f"/api/micro-applications/{asset_id}/sheets"
    fake_google.set(2, 0, "Mug")
    op = (await client.post(f"{url}/preview", headers=bearer(owner))).json()
    fake_broker.down = True
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.status_code == 503
    body = {
        "collection": "requests",
        "spreadsheet": fake_google.SPREADSHEET,
        "sheet_title": "Requests",
        "account_mode": "per_user",
        "columns": COLUMNS,
    }
    r = await client.put(url, json=body, headers=bearer(owner))
    assert r.status_code == 409 and r.json()["code"] == "sheet_sync_in_progress"
    assert (await client.post(f"{url}/preview", headers=bearer(owner))).json()[
        "code"
    ] == "sheet_sync_in_progress"
    fake_broker.down = False
    fake_google.fail_write = "timeout"
    r = await client.post(f"{url}/operations/{op['id']}/apply", json={}, headers=bearer(owner))
    assert r.json()["google_status"] == "uncertain"
    fake_google.fail_write = None

    colleague = await mk_user(session)
    await session.commit()
    await client.put(
        f"/api/micro-applications/{asset_id}/access",
        json={"user_email": colleague.email, "permissions": ["app.control"], "can_open": True},
        headers=bearer(owner),
    )
    r = await client.post(f"{url}/operations/{op['id']}/check", headers=bearer(colleague))
    assert r.status_code == 403 and r.json()["code"] == "sheet_check_actor_only"


# ------------------------------------------- designing an app around a sheet


def test_field_names_and_types_come_from_the_sheet():
    assert inspect.field_name("Data złożenia", set()) == "data_zlozenia"
    assert inspect.field_name("1. Kwota (PLN)", {"c_1_kwota_pln"}) == "c_1_kwota_pln_2"
    cells = [("text", t) for t in ("nowy", "zatwierdzony", "nowy", "nowy")]
    assert inspect._suggest(cells, 4) == {"type": "enum", "values": ["nowy", "zatwierdzony"]}
    assert inspect._suggest([("number", 3.0), ("number", 4)], 2) == {"type": "integer"}
    assert inspect._suggest([("number", 3.5)], 1)["type"] == "decimal"
    assert inspect._suggest([("date", 46348)], 1) == {"type": "date"}
    assert inspect._suggest([("text", "22.11.2026")], 1) == {"type": "date"}
    assert inspect._suggest([("text", "tak"), ("text", "nie")], 2) == {"type": "boolean"}
    assert inspect._suggest([("text", "x"), ("number", 1)], 2) == {"type": "string"}


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_an_agent_reads_a_sheet_to_design_the_app_with_the_callers_account(
    client, session, fake_google
):
    alice = await mk_user(session)
    await session.commit()
    body = {"spreadsheet": f"https://docs.google.com/spreadsheets/d/{fake_google.SPREADSHEET}/"}
    r = await client.post("/api/integrations/google/inspect", json=body, headers=bearer(alice))
    assert r.status_code == 409 and r.json()["action"] == "connect_google"
    await _connect(client, alice, fake_google)
    fake_google.grid = [
        ["Nr", "Tytuł", "Kwota", "Złożono", "Status"],
        [1, "Laptop", 4999.99, ("DATE", 46348), "nowy"],
        [2, "Krzesło", 799, ("DATE", 46349), "nowy"],
        [3, "Monitor", 1200, ("DATE", 46350), "zatwierdzony"],
        [4, "Lampa", None, ("DATE", 46351), "nowy"],
    ]
    r = await client.post("/api/integrations/google/inspect", json=body, headers=bearer(alice))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["tab"] == "Requests" and out["sampled_rows"] == 4 and not out["already_linked"]
    cols = {c["header"]: c for c in out["columns"]}
    assert cols["Nr"]["suggested"] == {"type": "integer"} and cols["Nr"]["unique"]
    assert cols["Tytuł"]["field"] == "tytul" and cols["Tytuł"]["suggested"]["type"] == "string"
    assert cols["Kwota"]["suggested"]["type"] == "decimal" and cols["Kwota"]["filled"] == "3/4"
    assert cols["Złożono"]["suggested"] == {"type": "date"}
    assert cols["Status"]["suggested"] == {"type": "enum", "values": ["nowy", "zatwierdzony"]}
    r = await client.post(
        "/api/integrations/google/inspect", json={**body, "tab": "Nope"}, headers=bearer(alice)
    )
    assert r.status_code == 404 and r.json()["tabs"] == ["Requests"]


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_the_owners_row_limit_set_by_an_admin_caps_the_sync(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google)
    url = f"/api/micro-applications/{asset_id}/sheets"
    for row, title in ((2, "A"), (3, "B")):
        fake_google.set(row, 0, title)
    admin = await mk_user(session, role="admin")
    await session.commit()
    out = await patch_user(owner.id, PatchUserIn(sheet_max_rows=1), admin, session)
    assert out["sheet_max_rows"] == 1
    entry = await session.scalar(
        select(AuditLog).where(AuditLog.action == "user_sheet_rows_limit_changed")
    )
    assert entry is not None and entry.payload == {"from_rows": 5000, "to_rows": 1}
    r = await client.post(f"{url}/preview", headers=bearer(owner))
    assert r.status_code == 413 and r.json()["code"] == "sheet_too_large"
    assert r.json()["limit"] == 1
    assert (await client.get(url, headers=bearer(owner))).json()["row_limit"] == 1


def test_an_excel_file_on_drive_gets_its_own_code():
    resp = httpx.Response(
        400,
        json={
            "error": {
                "code": 400,
                "message": "This operation is not supported for this document. "
                "The document must not be an Office file.",
            }
        },
    )
    err = google._error(resp, sent=False)
    assert err.code == "google_office_file" and not err.retryable
    assert common.google_error(err).code == "google_office_file"


def test_a_date_formatted_cell_with_a_time_is_a_timestamp():
    fmt = {"effectiveFormat": {"numberFormat": {"type": "DATE"}}}
    assert inspect._kind({"effectiveValue": {"numberValue": 45689.0}, **fmt})[0] == "date"
    assert inspect._kind({"effectiveValue": {"numberValue": 45689.46}, **fmt})[0] == "datetime"


def test_text_timestamps_without_a_zone_are_read_in_the_sheets_zone():
    field = {"type": "timestamptz"}
    got = values.from_cell(field, "2025-02-01 11:08:44", tz="Europe/Paris")
    assert got == "2025-02-01T10:08:44.000Z"
    texts = [("text", "2025-02-01 11:08:44"), ("text", "2025-02-02 09:11:04")]
    assert inspect._suggest(texts, 2, "Europe/Paris") == {"type": "timestamptz"}
    assert inspect._suggest([("text", "2025-02-01"), ("text", "2025-02-02")], 2) == {"type": "date"}


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_an_automatic_sync_applies_both_sides_leaves_quiet_runs_no_trace_and_stops_at_conflicts(
    client, session, fake_google, fake_broker
):
    owner, asset_id = await _linked(client, session, fake_google, auto_sync=True)
    link = await session.scalar(select(SheetLink).where(SheetLink.asset_id == uuid.UUID(asset_id)))
    assert link is not None and link.auto_sync
    link_id, owner_id = link.id, owner.id
    settings = get_settings()

    async def tick(changed: bool = False) -> str:
        """A run whose turn came; `changed`: the broker reported an app write."""
        await session.execute(
            update(SheetLink)
            .where(SheetLink.id == link_id)
            .values(
                auto_checked_at=utc_now() - timedelta(hours=1),
                app_changed_at=utc_now() if changed else None,
            )
        )
        await session.commit()
        session.expire_all()
        return await auto.run(session, settings, link_id)

    async def operations() -> list[SheetOperation]:
        return list(
            await session.scalars(
                select(SheetOperation)
                .where(SheetOperation.link_id == link_id)
                .order_by(SheetOperation.created_at)
            )
        )

    def app_reads() -> int:
        return sum(1 for path, _ in fake_broker.calls if path.endswith("/sheets/read"))

    monitor = fake_broker.add("Monitor")
    assert await tick(changed=True) == "synced"
    assert [fake_google.cell(2, c) for c in range(3)] == ["Monitor", None, "submitted"]
    # Nothing moved on either side: the run reads both and stores nothing.
    assert await tick() == "idle"
    assert len(await operations()) == 1
    # The sheet hashes as that run found it and the app reported nothing:
    # only Google is read.
    reads = app_reads()
    assert await tick() == "idle"
    assert app_reads() == reads
    # A person's preview reads both sides whatever the hash.
    r = await client.post(
        f"/api/micro-applications/{asset_id}/sheets/preview", headers=bearer(owner)
    )
    assert r.status_code == 201, r.text
    assert app_reads() == reads + 1
    # Left aside, so the automatic runs below do not wait for it.
    await session.execute(
        update(SheetOperation)
        .where(SheetOperation.id == uuid.UUID(r.json()["id"]))
        .values(created_at=utc_now() - timedelta(hours=1))
    )
    await session.commit()

    fake_broker.rows[monitor].update(title="Monitor 27", revision=2)
    assert await tick(changed=True) == "synced"
    assert fake_google.cell(2, 0) == "Monitor 27"
    # Only an export: no base row is rewritten for the app's side, and the
    # record did not move.
    applied = (await operations())[-1]
    assert applied.export["rows"] == {} and not any(applied.export["local_base"].values())

    fake_google.set(2, 1, "for the reception")
    assert await tick() == "synced"
    assert fake_broker.rows[monitor]["description"] == "for the reception"

    # A preview with only something to report (a synced row deleted from
    # the sheet) leaves no row either: a person's preview shows it.
    chair = fake_broker.add("Chair")
    assert await tick(changed=True) == "synced"
    assert fake_google.cell(3, 0) == "Chair"
    fake_google.grid = fake_google.grid[:2]
    before = len(await operations())
    assert await tick() == "idle"
    assert len(await operations()) == before
    del fake_broker.rows[chair]

    # Both sides changed one cell: a person decides, the owner hears of it once.
    fake_google.set(2, 0, "Monitor 32")
    fake_broker.rows[monitor].update(
        title="Monitor 24", revision=fake_broker.rows[monitor]["revision"] + 1
    )
    assert await tick(changed=True) == "stopped"
    session.expire_all()
    stopped = await session.get(SheetLink, link_id)
    assert stopped is not None and stopped.auto_error == "conflicts"
    assert stopped.auto_next_at == stopped.auto_checked_at + timedelta(
        seconds=settings.google_sheets_poll_seconds
    )
    assert fake_google.cell(2, 0) == "Monitor 32"
    # Only the poll interval brings another look, and then the preview waits.
    assert await tick(changed=True) == "held"
    await session.execute(
        update(SheetLink).where(SheetLink.id == link_id).values(auto_next_at=utc_now())
    )
    await session.commit()
    assert await tick() == "waiting"
    session.expire_all()
    waiting = await session.get(SheetLink, link_id)
    assert waiting is not None and waiting.auto_checked_at > utc_now() - timedelta(minutes=1)
    assert waiting.auto_next_at == waiting.auto_checked_at + timedelta(
        seconds=settings.google_sheets_poll_seconds
    )
    entries, _ = await inbox.page(get_redis(), owner_id, before=None, limit=10, unread_only=False)
    (entry,) = entries
    assert entry.payload["c"] == "sheets.auto_sync_stopped"
    assert entry.payload["x"]["reason"] == "conflicts"
    ops = await operations()
    assert len([op for op in ops if op.auto]) == before and len(ops) == before + 1


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_a_passing_error_is_retried_with_a_growing_delay(
    client, session, fake_google, fake_broker
):
    _, asset_id = await _linked(client, session, fake_google, auto_sync=True)
    link = await session.scalar(select(SheetLink).where(SheetLink.asset_id == uuid.UUID(asset_id)))
    assert link is not None
    link_id = link.id
    settings = get_settings()
    fake_broker.add("Monitor")
    fake_broker.down = True

    async def retry_after(delay: int | None) -> timedelta:
        """Run with the previous retry `delay` seconds long (None: none); the next delay."""
        now = utc_now()
        await session.execute(
            update(SheetLink)
            .where(SheetLink.id == link_id)
            .values(
                auto_checked_at=now - timedelta(seconds=(delay or 0) + 30),
                auto_next_at=now - timedelta(seconds=30) if delay else None,
            )
        )
        await session.commit()
        session.expire_all()
        assert await auto.run(session, settings, link_id) == "retry"
        session.expire_all()
        got = await session.get(SheetLink, link_id)
        assert got is not None and got.auto_error is None
        assert got.auto_checked_at is not None and got.auto_next_at is not None
        return got.auto_next_at - got.auto_checked_at

    assert await retry_after(None) == timedelta(seconds=10)
    assert await retry_after(10) == timedelta(seconds=20)
    assert await retry_after(40) == timedelta(seconds=80)
    poll = settings.google_sheets_poll_seconds
    assert await retry_after(poll) == timedelta(seconds=poll)
    # Within the delay nothing runs, however the link was queued.
    session.expire_all()
    assert await auto.run(session, settings, link_id) == "held"
    assert link_id not in await auto.due_links(session, settings)


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_an_automatic_sync_needs_the_owners_account(client, session, fake_google):
    owner = await mk_user(session)
    await session.commit()
    op, _ = await _published(client, session, owner)
    await _connect(client, owner, fake_google)
    r = await client.put(
        f"/api/micro-applications/{op['asset_id']}/sheets",
        json={
            "collection": "requests",
            "spreadsheet": fake_google.SPREADSHEET,
            "sheet_title": "Requests",
            "columns": COLUMNS,
            "account_mode": "per_user",
            "auto_sync": True,
        },
        headers=bearer(owner),
    )
    assert r.status_code == 400 and r.json()["code"] == "auto_sync_needs_owner_account"


# ------------------------------------------------- activity-driven syncs


class FakePool:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((name, args, kwargs))

    def links(self) -> list[str]:
        return [args[0] for _, args, _ in self.jobs]


@pytest.fixture
def fake_pool(monkeypatch):
    pool = FakePool()

    async def get_pool() -> FakePool:
        return pool

    monkeypatch.setattr(queue, "get_pool", get_pool)
    return pool


async def _auto_link(client, session, fake_google) -> tuple[Any, str, SheetLink, uuid.UUID]:
    owner, asset_id = await _linked(client, session, fake_google, auto_sync=True)
    link = await session.scalar(select(SheetLink).where(SheetLink.asset_id == uuid.UUID(asset_id)))
    env_id = await session.scalar(
        select(MicroAppEnvironment.id).where(MicroAppEnvironment.asset_id == uuid.UUID(asset_id))
    )
    assert link is not None and env_id is not None
    return owner, asset_id, link, env_id


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_the_broker_report_counts_open_pages_and_records_a_changed_linked_collection(
    client, session, fake_google, fake_pool
):
    owner, asset_id, link, env_id = await _auto_link(client, session, fake_google)
    link_id, auth = link.id, bearer(owner)

    async def report(**app: Any) -> None:
        r = await client.post(
            "/api/internal/microapps/report",
            headers=SVC,
            json={"incarnation": "inc-1", "apps": [{"asset_id": asset_id, **app}], "logs": []},
        )
        assert r.status_code == 200, r.text

    async def changed_at() -> Any:
        session.expire_all()
        got = await session.get(SheetLink, link_id)
        assert got is not None
        return got.app_changed_at

    await report(
        state="sleeping", realtime={"sockets": 3, "people": 2}, changed_collections=["requests"]
    )
    # Recorded on the link for the sweeper; the report queues nothing.
    first = await changed_at()
    assert first is not None and fake_pool.jobs == []
    stats = await session.get(MicroAppStats, env_id, populate_existing=True)
    assert stats is not None and (stats.realtime_sockets, stats.realtime_people) == (3, 2)
    status = (await client.get(f"/api/micro-applications/{asset_id}", headers=auth)).json()
    assert status["runtime"]["realtime"] == {"sockets": 3, "people": 2}

    # Another collection, or none, is no reason to read the sheet.
    await report(state="ready", realtime={"sockets": "x"}, changed_collections=["comments"])
    await report(state="ready")
    assert await changed_at() == first and fake_pool.jobs == []
    stats = await session.get(MicroAppStats, env_id, populate_existing=True)
    assert stats is not None and (stats.realtime_sockets, stats.realtime_people) == (0, 0)


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_the_sweeper_reads_the_sheet_by_the_apps_activity(client, session, fake_google):
    _, _, link, env_id = await _auto_link(client, session, fake_google)
    link_id = link.id
    settings = get_settings()
    poll = settings.google_sheets_poll_seconds
    active = settings.google_sheets_active_poll_seconds

    async def due(
        state: str | None,
        sockets: int = 0,
        checked: int | None = None,
        sampled: int = 0,
        desired: str = "enabled",
        changed: int | None = None,
        next_in: int | None = None,
    ) -> bool:
        """Whether a sweep queues the link; ages in seconds."""
        now = utc_now()

        def ago(seconds: int | None) -> Any:
            return now - timedelta(seconds=seconds) if seconds is not None else None

        await session.execute(
            update(SheetLink)
            .where(SheetLink.id == link_id)
            .values(
                auto_checked_at=ago(checked),
                app_changed_at=ago(changed),
                auto_next_at=now + timedelta(seconds=next_in) if next_in else None,
            )
        )
        await session.execute(
            update(MicroAppEnvironment)
            .where(MicroAppEnvironment.id == env_id)
            .values(desired_state=desired, updated_at=now - timedelta(hours=1))
        )
        stats = await session.get(MicroAppStats, env_id) or MicroAppStats(environment_id=env_id)
        stats.runtime_state = state
        stats.runtime_sampled_at = now - timedelta(seconds=sampled)
        stats.realtime_sockets = sockets
        session.add(stats)
        await session.commit()
        return link_id in await auto.due_links(session, settings)

    # Asleep, never synced: nothing.
    assert not await due("sleeping")
    # Awake: every google_sheets_poll_seconds, so waking up after a longer
    # sleep syncs at once and a short nap does not.
    assert await due("ready")
    assert not await due("ready", checked=60)
    assert await due("ready", checked=poll)
    # People have it open: every google_sheets_active_poll_seconds.
    assert not await due("ready", sockets=2, checked=active - 10)
    assert await due("sleeping", sockets=2, checked=active)
    # Asleep, suspended or not heard of lately: never, however old the sync.
    assert not await due("sleeping", checked=3600)
    assert not await due("ready", checked=3600, desired="suspended")
    assert not await due("ready", sockets=2, checked=3600, sampled=120)
    # A sample from a broker no longer alive says the app sleeps.
    await get_redis().set(BROKER_HEARTBEAT_KEY, json.dumps({"incarnation": "inc-2"}), ex=60)
    try:
        stats = await session.get(MicroAppStats, env_id)
        assert stats is not None
        stats.broker_incarnation = "inc-1"
        await session.commit()
        assert not await due("ready", checked=3600)
    finally:
        await get_redis().delete(BROKER_HEARTBEAT_KEY)
    # An app change since the last run: due whatever the app does now, but
    # not within 10 seconds of the last run.
    assert await due("sleeping", checked=15, changed=5)
    assert not await due("sleeping", checked=5, changed=2)
    assert not await due("sleeping", checked=30, changed=40)
    # A retry's delay or a waiting preview holds the link back.
    assert not await due("ready", checked=3600, changed=5, next_in=30)
    # The sweep writes nothing.
    session.expire_all()
    got = await session.get(SheetLink, link_id)
    assert got is not None and got.auto_checked_at is not None
    assert utc_now() - got.auto_checked_at > timedelta(minutes=59)


@needs_pg
@pytest.mark.usefixtures("apps_db")
async def test_reading_the_apps_data_through_ics_syncs_a_sheet_not_looked_at_lately(
    client, session, fake_google, fake_pool, monkeypatch
):
    owner, asset_id, link, _ = await _auto_link(client, session, fake_google)

    async def exported(settings, method, path, body=None, timeout=15.0):
        return {"collections": []}

    monkeypatch.setattr(document, "broker_admin", exported)
    url = f"/api/micro-applications/{asset_id}/document"
    assert (await client.get(url, headers=bearer(owner))).status_code == 200
    assert fake_pool.links() == [str(link.id)]

    await session.execute(
        update(SheetLink).where(SheetLink.id == link.id).values(auto_checked_at=utc_now())
    )
    await session.commit()
    assert (await client.get(url, headers=bearer(owner))).status_code == 200
    assert len(fake_pool.jobs) == 1


def test_sheet_syncs_run_on_their_own_queue():
    from app.jobs import sheets_worker, worker

    main = {getattr(f, "name", getattr(f, "__name__", "")) for f in worker.WorkerSettings.functions}
    main |= {c.name for c in worker.WorkerSettings.cron_jobs}
    assert not any(name.startswith("sheets") for name in main)
    own = sheets_worker.WorkerSettings
    assert own.queue_name == get_settings().google_sheets_queue_name != "arq:queue"
    assert {getattr(f, "name", getattr(f, "__name__", "")) for f in own.functions} == {
        "sheets_auto_sweeper",
        "sheets_auto_sync",
    }
    assert own.max_jobs == get_settings().google_sheets_max_jobs
