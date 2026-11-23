"""Reading an unlinked spreadsheet for whoever designs an app around it
(ADR-0031): its tabs, the headers of one tab and, per column, the field type
its values suggest, so an agent can model the collection on the sheet as it
is and link it without asking anyone to change the file."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain_errors import NotFoundError
from app.models import SheetLink, User

from . import google, values
from .common import google_error, token_for
from .compare import column_letter, norm_header
from .links import spreadsheet_id_of

SAMPLE_ROWS = 200
_SHOWN = 5
# An enum: at most this many distinct texts, each seen at least twice on average.
_ENUM_MAX = 12
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_IDENT = re.compile(r"[^a-z0-9]+")
# NFKD strips accents but has no decomposition for the Polish l with stroke.
_STROKE = {0x142: "l", 0x141: "L"}


def field_name(header: str, taken: set[str]) -> str:
    """A field name for a header: ASCII, lower case, underscores, unique."""
    text = unicodedata.normalize("NFKD", header.translate(_STROKE))
    text = _IDENT.sub("_", text.encode("ascii", "ignore").decode().lower()).strip("_")
    name = (text or "column")[:56]
    if name[0].isdigit():
        name = f"c_{name}"
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name}_{n}", n + 1
    taken.add(candidate)
    return candidate


def _kind(cell: dict[str, Any]) -> tuple[str, Any] | None:
    """(`bool` | `number` | `date` | `datetime` | `text`, value) of a cell."""
    value = cell.get("effectiveValue")
    if not value:
        return None
    if "boolValue" in value:
        return "bool", value["boolValue"]
    if "numberValue" in value:
        fmt = ((cell.get("effectiveFormat") or {}).get("numberFormat") or {}).get("type")
        # A DATE format may still hide a time of day (a custom pattern with
        # hours): a fractional serial is a timestamp, not a day.
        if fmt == "DATE" and float(value["numberValue"]).is_integer():
            return "date", value["numberValue"]
        if fmt == "DATE":
            return "datetime", value["numberValue"]
        if fmt == "DATE_TIME":
            return "datetime", value["numberValue"]
        return "number", value["numberValue"]
    if "stringValue" in value:
        text = str(value["stringValue"]).strip()
        return ("text", text) if text else None
    return "text", cell.get("formattedValue")


def _suggest(cells: list[tuple[str, Any]], rows: int, tz: str = "UTC") -> dict[str, Any]:
    """The field a column's non-empty cells fit best; text when in doubt."""
    kinds = {k for k, _ in cells}
    raw = [v for _, v in cells]
    if not cells:
        return {"type": "string"}
    if kinds == {"bool"}:
        return {"type": "boolean"}
    if kinds == {"date"}:
        return {"type": "date"}
    if kinds <= {"date", "datetime"}:
        return {"type": "timestamptz"}
    if kinds == {"number"}:
        if all(float(v).is_integer() for v in raw):
            return {"type": "integer"}
        return {"type": "decimal", "scale": 2}
    if kinds == {"text"}:
        texts = [str(v) for v in raw]
        # A date reads only the day, so text with a time of day is offered as
        # a timestamp first, or the time would be lost.
        timed = any(len(t.strip()) > 10 for t in texts)
        candidates = [{"type": "boolean"}, *([{"type": "timestamptz"}] if timed else [])]
        for field in (*candidates, {"type": "date"}):
            try:
                for t in texts:
                    values.from_cell(field, t, tz=tz)
            except values.CellError:
                continue
            return field
        if all(_UUID.match(t) for t in texts):
            return {"type": "uuid"}
        distinct = sorted(set(texts))
        if len(distinct) <= _ENUM_MAX and len(texts) >= 2 * len(distinct) and rows >= 4:
            return {"type": "enum", "values": distinct}
        return {"type": "string", "maxLength": max(200, 2 * max(len(t) for t in texts))}
    return {"type": "string"}


async def inspect(
    session: AsyncSession,
    settings: Settings,
    user: User,
    spreadsheet: str,
    tab: str | None,
) -> dict[str, Any]:
    spreadsheet_id = spreadsheet_id_of(spreadsheet)
    linked = await session.scalar(
        select(SheetLink.asset_id).where(SheetLink.spreadsheet_id == spreadsheet_id)
    )
    token = await token_for(session, settings, user.id)
    await session.commit()
    try:
        meta = await google.spreadsheet_meta(token, spreadsheet_id)
        tabs = [s["properties"] for s in meta.get("sheets", [])]
        tz = (meta.get("properties") or {}).get("timeZone") or "UTC"
        chosen = next((t for t in tabs if tab is None or t["title"] == tab), None)
        if chosen is None:
            raise NotFoundError(
                "sheet_tab_not_found",
                f"the spreadsheet has no tab {tab!r}",
                extra={"tabs": [t["title"] for t in tabs][:50]},
            )
        size = chosen.get("gridProperties", {})
        width = max(int(size.get("columnCount", 26)), 1)
        body = await google.grid(
            token,
            spreadsheet_id,
            f"{google.a1_tab(chosen['title'])}!A1:{column_letter(width - 1)}{SAMPLE_ROWS + 1}",
        )
    except google.GoogleError as e:
        raise google_error(e) from e
    data = ((body.get("sheets") or [{}])[0].get("data") or [{}])[0].get("rowData") or []
    grid = [list(r.get("values") or []) for r in data]
    header = grid[0] if grid else []
    body_rows = [r for r in grid[1:] if any(_kind(c) for c in r)]
    taken: set[str] = set()
    seen: set[str] = set()
    columns = []
    for i, cell in enumerate(header):
        name = str(cell.get("formattedValue") or "").strip()
        if not name:
            continue
        cells = [k for r in body_rows if i < len(r) and (k := _kind(r[i])) is not None]
        texts = [str(c[1]) for c in cells]
        columns.append(
            {
                "header": name,
                "column": column_letter(i),
                "field": field_name(name, taken),
                "suggested": _suggest(cells, len(body_rows), tz),
                "filled": f"{len(cells)}/{len(body_rows)}",
                "unique": bool(cells) and len(set(texts)) == len(texts),
                "duplicate_header": norm_header(name) in seen,
                "samples": [
                    r[i].get("formattedValue")
                    for r in body_rows[:_SHOWN]
                    if i < len(r) and r[i].get("formattedValue") is not None
                ],
            }
        )
        seen.add(norm_header(name))
    return {
        "spreadsheet_id": spreadsheet_id,
        "title": (meta.get("properties") or {}).get("title"),
        "time_zone": tz,
        "tabs": [t["title"] for t in tabs],
        "tab": chosen["title"],
        "sampled_rows": len(body_rows),
        # Types are guessed from the first rows only.
        "more_rows": len(grid) > SAMPLE_ROWS,
        "columns": columns,
        "already_linked": linked is not None,
    }
