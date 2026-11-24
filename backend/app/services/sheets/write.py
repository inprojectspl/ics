"""Writing a sync's cells to the file and checking a write whose answer was
lost (ADR-0031, ADR-0033). The file is read again right before the write,
so cells land on the rows as they are then; every tab's cells go in one
`batchUpdate`, and nothing is ever sent twice."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain_errors import AccessDeniedError, DomainError
from app.models import Asset, MicroAppEnvironment, SheetLink, SheetMapping, SheetOperation, User
from app.util import now

from . import google, links, values
from .book import Book, Sheet, Tab
from .common import (
    fetch_book,
    grant_user_of,
    operation,
    placed,
    row_limit,
    runnable_link,
    save_base,
    token_for,
)

# A `pending` write younger than this may still be on its way.
PENDING_GRACE = timedelta(seconds=90)


# -------------------------------------------------------------- the sheet write


class _SheetMovedError(Exception):
    pass


# A cell to write, kept compact in the operation (a first sync writes many):
# [sheet_id, row in the tab, column, field, value], grouped by mapping id.
Cell = list[Any]


def _cells(
    part: dict[str, Any], own: dict[str, Any], created: Mapping[str, Any], sheet: Sheet
) -> tuple[list[Cell], dict[str, list[int]]]:
    """Every cell of one mapping to write, placed on its tabs as they are now
    (a touched row that only moved is followed), and the tab row of each
    written record. Raises _SheetMovedError when a touched row changed."""
    where = placed(part, sheet)
    if where is None:
        raise _SheetMovedError
    cells: list[Cell] = []
    rows: dict[str, list[int]] = {}

    def put(tab: Tab, row: int, record_id: str, data: Mapping[str, Any]) -> None:
        rows[record_id] = [tab.sheet_id, row]
        cells.extend(
            [tab.sheet_id, row, tab.cols[f], f, v] for f, v in data.items() if f in tab.cols
        )

    for u in part["updates"]:
        put(*sheet.at(where[u["row"]]), u["record_id"], own["remote_base"][u["record_id"]])
    for c in part["creates"]:
        put(*sheet.at(where[c["row"]]), c["record_id"], created.get(c["record_id"], {}))
    added: dict[int, int] = {}
    for a in part["appends"]:
        tab = sheet.tab(a.get("sheet_id")) or sheet.append_tab()
        if tab is None:
            raise _SheetMovedError
        n = added.get(tab.sheet_id, 0)
        added[tab.sheet_id] = n + 1
        blank = set(a.get("blank") or ())
        data = {f: v for f, v in a["values"].items() if f not in blank}
        put(tab, tab.height + 2 + n, a["record_id"], data)
    return cells, rows


def _requests(
    cells: Mapping[str, list[Cell]],
    fields: Mapping[str, Mapping[str, dict[str, Any]]],
    row_counts: Mapping[int, int],
) -> list[dict[str, Any]]:
    """Per tab, one `appendDimension` when its rows go past the grid, then
    `updateCells` per run of adjacent cells in a row (dates in runs of their
    own, since their mask also sets the number format)."""
    requests: list[dict[str, Any]] = []
    flat = [
        (sid, row, col, fields[mid][f], v)
        for mid, own in cells.items()
        for sid, row, col, f, v in own
    ]
    last: dict[int, int] = {}
    for sid, row, *_ in flat:
        last[sid] = max(last.get(sid, 0), row)
    for sheet_id, row in sorted(last.items()):
        if row > row_counts[sheet_id]:
            requests.append(
                {
                    "appendDimension": {
                        "sheetId": sheet_id,
                        "dimension": "ROWS",
                        "length": row - row_counts[sheet_id],
                    }
                }
            )
    runs: list[tuple[int, int, int, bool, list[dict[str, Any]]]] = []
    for sid, row, col, field, value in sorted(flat, key=lambda c: c[:3]):
        data = values.to_cell(field, value)
        is_date = field["type"] == "date"
        prev = runs[-1] if runs else None
        if (
            prev
            and prev[0] == sid
            and prev[1] == row
            and prev[2] + len(prev[4]) == col
            and prev[3] == is_date
        ):
            prev[4].append(data)
        else:
            runs.append((sid, row, col, is_date, [data]))
    for sheet_id, row, col, is_date, run in runs:
        requests.append(
            {
                "updateCells": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": col,
                        "endColumnIndex": col + len(run),
                    },
                    "rows": [{"values": run}],
                    "fields": "userEnteredValue,userEnteredFormat.numberFormat"
                    if is_date
                    else "userEnteredValue",
                }
            }
        )
    return requests


async def _fail_write(session: AsyncSession, op: SheetOperation, status: str, code: str) -> None:
    op.google_status = status
    op.error = code[:64]
    await session.commit()


async def _read(
    session: AsyncSession,
    settings: Settings,
    asset: Asset,
    link: SheetLink,
    env: MicroAppEnvironment,
    op: SheetOperation,
) -> tuple[list[SheetMapping], dict[str, dict[str, dict[str, Any]]], str, Book]:
    """The mappings, each one's field definitions, the token of the
    operation's Google account and the file as it is now."""
    mappings = await links.mappings_of(session, link)
    manifest = await links.manifest_of(session, env)
    fields = {str(m.id): links.field_defs(manifest, m) for m in mappings}
    limit = await row_limit(session, settings, asset)
    token = await token_for(session, settings, grant_user_of(op))
    await session.commit()  # no transaction across the call below
    return mappings, fields, token, await fetch_book(token, link, mappings, limit)


async def write(
    session: AsyncSession,
    settings: Settings,
    asset: Asset,
    link: SheetLink,
    env: MicroAppEnvironment,
    op: SheetOperation,
) -> None:
    """Read the file again, place the cells on its tabs as they are now and
    send them all in one `batchUpdate`. A changed link or sheet stops the
    write: the next preview offers whatever is still missing."""
    await session.refresh(link)
    if link.revision != op.link_revision:
        await _fail_write(session, op, "failed", "sheet_link_changed")
        return
    plan = op.export or {}
    parts = op.preview["mappings"]
    try:
        mappings, fields, token, book = await _read(session, settings, asset, link, env, op)
        cells: dict[str, list[Cell]] = {}
        rows: dict[str, dict[str, list[int]]] = {}
        for m in mappings:
            mid = str(m.id)
            cells[mid], rows[mid] = _cells(
                parts[mid], plan["mappings"][mid], plan.get("created") or {}, book[mid]
            )
            if any(c[3] not in fields[mid] for c in cells[mid]):
                raise _SheetMovedError
    except _SheetMovedError:
        await _fail_write(session, op, "failed", "sheet_changed")
        return
    except DomainError as e:
        await _fail_write(session, op, "failed", e.code)
        return
    op.export = {**plan, "cells": cells, "remote_rows": rows}
    await session.commit()
    if any(cells.values()):
        row_counts = {t.sheet_id: t.row_count for s in book.values() for t in s.tabs}
        try:
            await google.batch_update(
                token, link.spreadsheet_id, _requests(cells, fields, row_counts)
            )
        except google.GoogleError as e:
            await _fail_write(session, op, "uncertain" if e.sent else "failed", e.code)
            return
        except Exception:
            # Whatever broke after the request left, its outcome is unknown.
            await _fail_write(session, op, "uncertain", "google_write_unknown")
            raise
    await _confirm(session, op)


async def _confirm(session: AsyncSession, op: SheetOperation) -> None:
    export = op.export or {}
    remote_rows = export.get("remote_rows") or {}
    for mid, own in (export.get("mappings") or {}).items():
        await save_base(session, mid, own.get("remote_base", {}), remote_rows.get(mid))
    op.google_status = "confirmed"
    op.error = None
    await session.commit()


# -------------------------------------------------------------------- check


async def check(
    session: AsyncSession, settings: Settings, user: User, asset_id: UUID, op_id: UUID
) -> SheetOperation:
    """Settle an `uncertain` write, or a `pending` one a crash left behind, by
    reading its cells back: all of them as written means Google applied it
    (a batchUpdate is all or nothing). It never writes."""
    asset, link, env, _ = await runnable_link(session, user, asset_id)
    op = await operation(session, link, op_id)
    if op.google_status == "pending" and now() - op.updated_at < PENDING_GRACE:
        return op  # May still be on its way.
    if op.google_status not in links.UNSETTLED:
        return op
    if link.account_mode == "per_user" and op.actor_id != user.id:
        # It reads with that person's own Google account.
        raise AccessDeniedError(
            "sheet_check_actor_only", "only the person who ran this sync can check it"
        )
    cells: dict[str, list[Cell]] = (op.export or {}).get("cells") or {}
    written = False
    if any(cells.values()):
        _, fields, _, book = await _read(session, settings, asset, link, env, op)
        written = all(
            mid in book and _cell_equals(book[mid], cell, fields.get(mid, {}))
            for mid, own in cells.items()
            for cell in own
        )
    op = await operation(session, link, op.id, lock=True)
    if op.google_status not in links.UNSETTLED:
        await session.commit()
        return op
    if written:
        await _confirm(session, op)
    else:
        # Never sent, not there or changed since: the base keeps the old
        # values, so the next preview offers the write again.
        await _fail_write(session, op, "failed", "google_not_applied")
    return op


def _cell_equals(sheet: Sheet, cell: Cell, fields: Mapping[str, Any]) -> bool:
    sheet_id, row, _, name, value = cell
    field, tab = fields.get(name), sheet.tab(sheet_id)
    if field is None or tab is None:
        return False
    # A row past the tab's last one is empty, not the next tab's first.
    raw = sheet.cell(tab.first + row, sheet.cols[name]) if 2 <= row < tab.height + 2 else None
    try:
        return bool(values.from_cell(field, raw, tz=sheet.tz) == value)
    except values.CellError:
        return False
