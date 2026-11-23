"""Writing a sync's cells to the sheet and checking a write whose answer was
lost (ADR-0031). The sheet is read again right before the write, so cells
land on the rows as they are then, and nothing is ever sent twice."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain_errors import AccessDeniedError, DomainError
from app.models import Asset, MicroAppEnvironment, SheetLink, SheetOperation, User
from app.util import now

from . import google, links, values
from .common import (
    fetch_sheet,
    grant_user_of,
    operation,
    placed,
    row_limit,
    runnable_link,
    save_base,
    token_for,
)
from .compare import Sheet

# A `pending` write younger than this may still be on its way.
PENDING_GRACE = timedelta(seconds=90)


# -------------------------------------------------------------- the sheet write


class _SheetMovedError(Exception):
    pass


def _cells(
    link: SheetLink, op: SheetOperation, sheet: Sheet
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Every cell to write, placed on the sheet as it is now (a touched row
    that only moved is followed), and the row of each written record.
    Raises _SheetMovedError when a touched row changed."""
    preview, plan = op.preview, op.export or {}
    where = placed(preview, link, sheet)
    if where is None:
        raise _SheetMovedError
    cols: dict[str, int] = preview["sheet"]["cols"]
    cells: list[dict[str, Any]] = []
    rows: dict[str, int] = {}

    def put(row: int, record_id: str, data: Mapping[str, Any]) -> None:
        rows[record_id] = row
        cells.extend(
            {"row": row, "col": cols[f], "field": f, "value": v}
            for f, v in data.items()
            if f in cols
        )

    for u in preview["updates"]:
        put(where[u["row"]], u["record_id"], plan["remote_base"][u["record_id"]])
    for c in preview["creates"]:
        put(where[c["row"]], c["record_id"], plan["created"].get(c["record_id"], {}))
    for i, a in enumerate(preview["appends"]):
        put(len(sheet.rows) + 2 + i, a["record_id"], a["values"])
    return cells, rows


def _requests(
    cells: list[dict[str, Any]], fields: Mapping[str, dict[str, Any]], sheet: Sheet
) -> list[dict[str, Any]]:
    """`updateCells` per run of adjacent cells in a row (dates in runs of
    their own, since their mask also sets the number format), after one
    `appendDimension` when the rows go past the grid."""
    requests: list[dict[str, Any]] = []
    last_row = max((c["row"] for c in cells), default=0)
    if last_row > sheet.row_count:
        requests.append(
            {
                "appendDimension": {
                    "sheetId": sheet.sheet_id,
                    "dimension": "ROWS",
                    "length": last_row - sheet.row_count,
                }
            }
        )
    runs: list[tuple[int, int, bool, list[dict[str, Any]]]] = []
    for cell in sorted(cells, key=lambda c: (c["row"], c["col"])):
        field = fields[cell["field"]]
        data = values.to_cell(field, cell["value"])
        is_date = field["type"] == "date"
        last = runs[-1] if runs else None
        if (
            last
            and last[0] == cell["row"]
            and last[1] + len(last[3]) == cell["col"]
            and last[2] == is_date
        ):
            last[3].append(data)
        else:
            runs.append((cell["row"], cell["col"], is_date, [data]))
    for row, col, is_date, run in runs:
        requests.append(
            {
                "updateCells": {
                    "range": {
                        "sheetId": sheet.sheet_id,
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


async def write(
    session: AsyncSession,
    settings: Settings,
    asset: Asset,
    link: SheetLink,
    env: MicroAppEnvironment,
    op: SheetOperation,
) -> None:
    """Read the sheet again, place the cells on it as it is now and send them
    in one `batchUpdate`. A changed link or sheet stops the write: the next
    preview offers whatever is still missing."""
    await session.refresh(link)
    if link.revision != op.link_revision:
        await _fail_write(session, op, "failed", "sheet_link_changed")
        return
    try:
        fields = links.field_defs(await links.manifest_of(session, env), link)
        limit = await row_limit(session, settings, asset)
        token = await token_for(session, settings, grant_user_of(op))
        await session.commit()
        sheet = await fetch_sheet(token, link, limit)
        cells, rows = _cells(link, op, sheet)
        if any(c["field"] not in fields for c in cells):
            raise _SheetMovedError
    except _SheetMovedError:
        await _fail_write(session, op, "failed", "sheet_changed")
        return
    except DomainError as e:
        await _fail_write(session, op, "failed", e.code)
        return
    op.export = {**(op.export or {}), "cells": cells, "remote_rows": rows}
    await session.commit()
    if cells:
        try:
            await google.batch_update(token, link.spreadsheet_id, _requests(cells, fields, sheet))
        except google.GoogleError as e:
            await _fail_write(session, op, "uncertain" if e.sent else "failed", e.code)
            return
        except Exception:
            # Whatever broke after the request left, its outcome is unknown.
            await _fail_write(session, op, "uncertain", "google_write_unknown")
            raise
    await _confirm(session, link, op)


async def _confirm(session: AsyncSession, link: SheetLink, op: SheetOperation) -> None:
    export = op.export or {}
    await save_base(session, link.id, export.get("remote_base", {}), export.get("remote_rows"))
    op.google_status = "confirmed"
    op.error = None
    await session.commit()


# -------------------------------------------------------------------- check


async def check(
    session: AsyncSession, settings: Settings, user: User, asset_id: UUID, op_id: UUID
) -> tuple[SheetOperation, SheetLink]:
    """Settle an `uncertain` write, or a `pending` one a crash left behind, by
    reading its cells back: all of them as written means Google applied it
    (a batchUpdate is all or nothing). It never writes."""
    asset, link, env = await runnable_link(session, user, asset_id)
    op = await operation(session, link, op_id)
    if op.google_status == "pending" and now() - op.updated_at < PENDING_GRACE:
        return op, link  # May still be on its way.
    if op.google_status not in ("uncertain", "pending"):
        return op, link
    if link.account_mode == "per_user" and op.actor_id != user.id:
        # It reads with that person's own Google account.
        raise AccessDeniedError(
            "sheet_check_actor_only", "only the person who ran this sync can check it"
        )
    cells = (op.export or {}).get("cells")
    written = False
    if cells:
        fields = links.field_defs(await links.manifest_of(session, env), link)
        limit = await row_limit(session, settings, asset)
        token = await token_for(session, settings, grant_user_of(op))
        await session.commit()
        sheet = await fetch_sheet(token, link, limit)
        written = all(_cell_equals(sheet, c, fields.get(c["field"])) for c in cells)
    op = await operation(session, link, op.id, lock=True)
    if op.google_status not in ("uncertain", "pending"):
        await session.commit()
        return op, link
    if written:
        await _confirm(session, link, op)
    else:
        # Never sent, not there or changed since: the base keeps the old
        # values, so the next preview offers the write again.
        await _fail_write(session, op, "failed", "google_not_applied")
    return op, link


def _cell_equals(sheet: Sheet, cell: dict[str, Any], field: dict[str, Any] | None) -> bool:
    if field is None:
        return False
    raw = sheet.cell(cell["row"], cell["col"])
    try:
        return bool(values.from_cell(field, raw, tz=sheet.tz) == cell["value"])
    except values.CellError:
        return False
