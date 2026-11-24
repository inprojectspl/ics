"""Reading the linked tabs of a spreadsheet file (ADR-0031, ADR-0033).

`read_book` reads every linked tab at once: one metadata call, one for the
header rows, one for the linked columns. The tabs of one mapping become one
`Sheet`: their rows one after another, each holding the linked columns in
the mapping's order, so a group of tabs (records split by month, state,
team...) compares like a single tab. Row numbers inside a `Sheet` count
across its tabs; `Sheet.at` gives the tab and its own row.
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from app.domain_errors import ConflictError, LimitExceededError, NotFoundError
from app.models import SheetMapping
from app.util import short_sha256

from . import google


def norm_header(name: Any) -> str:
    return str(name).strip().casefold()


def column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


# ---------------------------------------------------------------- the sheet


@dataclass
class Tab:
    """One tab of a mapping: where its rows start among the mapping's rows
    (`first`, 0-based), how many it has, and each linked field's column."""

    sheet_id: int
    title: str
    row_count: int
    first: int
    height: int
    cols: dict[str, int]
    append: bool = False

    def view(self) -> dict[str, Any]:
        return {
            "sheet_id": self.sheet_id,
            "title": self.title,
            "first": self.first,
            "cols": self.cols,
        }

    def ref(self) -> dict[str, Any]:
        """The tab as a mapping stores it."""
        return {
            "sheet_id": self.sheet_id,
            "title": self.title,
            **({"append": True} if self.append else {}),
        }


def tab_at(firsts: Sequence[int], row: int) -> tuple[int, int]:
    """The index of the tab holding a row counted across tabs whose rows
    start at `firsts`, and the row's number in that tab."""
    i = max(bisect.bisect_right(firsts, row - 2) - 1, 0)
    return i, row - firsts[i]


@dataclass
class Sheet:
    """The rows of one mapping's tabs, the linked columns in the mapping's
    order (`cols`: field -> index). Row 1 would be the header, so the first
    row of data is row 2, as in a single tab."""

    tz: str
    tabs: list[Tab]
    cols: dict[str, int]
    rows: list[list[Any]]
    _firsts: list[int] = dataclass_field(init=False, repr=False)
    _by_id: dict[int, Tab] = dataclass_field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._firsts = [t.first for t in self.tabs]
        self._by_id = {t.sheet_id: t for t in self.tabs}

    def cell(self, row: int, col: int) -> Any:
        cells = self.rows[row - 2] if 2 <= row < len(self.rows) + 2 else []
        return cells[col] if col < len(cells) else None

    def at(self, row: int) -> tuple[Tab, int]:
        """The tab of a row and the row's number in that tab."""
        i, own = tab_at(self._firsts, row)
        return self.tabs[i], own

    def tab(self, sheet_id: int | None) -> Tab | None:
        return self._by_id.get(sheet_id) if sheet_id is not None else None

    def append_tab(self) -> Tab | None:
        if len(self.tabs) == 1:
            return self.tabs[0]
        return next((t for t in self.tabs if t.append), None)


def tab_columns(columns: list[dict[str, Any]], header_row: list[Any], title: str) -> dict[str, int]:
    """Each linked field's column in a tab; a missing or doubled header stops
    the sync rather than read the wrong column."""
    header: dict[str, int] = {}
    doubled: set[str] = set()
    for i, name in enumerate(header_row):
        key = norm_header(name)
        if key in header:
            doubled.add(key)
        elif key:
            header[key] = i
    wanted = [c["header"] for c in columns]
    missing = [h for h in wanted if norm_header(h) not in header]
    if missing:
        raise ConflictError(
            "sheet_headers_missing",
            f"the first row of tab {title!r} lacks linked headers",
            extra={"missing": missing, "tab": title},
        )
    twice = [h for h in wanted if norm_header(h) in doubled]
    if twice:
        raise ConflictError(
            "sheet_headers_duplicate",
            f"a linked header appears more than once in the first row of tab {title!r}",
            extra={"duplicates": twice, "tab": title},
        )
    return {c["field"]: header[norm_header(c["header"])] for c in columns}


def header_range(tab: Mapping[str, Any], last_row: int = 1) -> str:
    """The A1 range of a tab's rows from the header to `last_row`, as wide
    as its grid."""
    width = max(int(tab.get("gridProperties", {}).get("columnCount", 26)), 1)
    return f"{google.a1_tab(tab['title'])}!A1:{column_letter(width - 1)}{last_row}"


# What one read of the file found: each mapping's `Sheet`, by mapping id.
Book = dict[str, Sheet]


def _resolve(
    mappings: Sequence[SheetMapping], found: list[dict[str, Any]]
) -> list[tuple[SheetMapping, dict[str, Any], dict[str, Any]]]:
    """Each linked tab as Google lists it now, with its mapping and how the
    mapping stores it: by id, or by name for a tab whose id is not pinned
    yet. A missing tab stops the sync: ICS never reads a vanished tab as all
    of its rows removed."""
    by_id = {int(t["sheetId"]): t for t in found}
    by_title = {t["title"]: t for t in found}
    claimed: set[int] = set()
    out = []
    for m in mappings:
        for want in m.tabs:
            sid = want.get("sheet_id")
            got = by_id.get(sid) if sid is not None else by_title.get(want["title"])
            if got is None:
                name = want["title"] if want.get("title") is not None else sid
                raise NotFoundError(
                    "sheet_tab_not_found",
                    f"the spreadsheet has no tab {name!r}",
                    extra={"tab": name, "tabs": [t["title"] for t in found][:50]},
                )
            if int(got["sheetId"]) in claimed:
                raise ConflictError(
                    "sheet_tab_ambiguous",
                    f"tab {got['title']!r} is linked twice",
                    extra={"tab": got["title"]},
                )
            claimed.add(int(got["sheetId"]))
            out.append((m, want, got))
    return out


async def read_book(
    token: str, spreadsheet_id: str, mappings: Sequence[SheetMapping], max_rows: int
) -> Book:
    """Every linked tab of the file: header rows first, then only the linked
    columns, so a wide or many-tabbed file costs no more than its linked
    cells. The row limit counts the rows of all linked tabs together."""
    meta = await google.spreadsheet_meta(token, spreadsheet_id)
    tz = str(meta.get("properties", {}).get("timeZone") or "UTC")
    order = _resolve(mappings, [s["properties"] for s in meta.get("sheets", [])])
    headers = await google.read_header_rows(
        token, spreadsheet_id, [header_range(got) for _, _, got in order]
    )
    layouts = []
    ranges: list[str] = []
    for (m, _, got), header_row in zip(order, headers, strict=True):
        cols = tab_columns(m.columns, header_row, got["title"])
        row_count = int(got.get("gridProperties", {}).get("rowCount", 1000))
        last_row = min(row_count, max_rows + 2)
        wanted = sorted(set(cols.values())) if last_row >= 2 else []
        a1 = google.a1_tab(got["title"])
        ranges += [f"{a1}!{column_letter(c)}2:{column_letter(c)}{last_row}" for c in wanted]
        layouts.append((cols, wanted, row_count))
    columns = await google.read_columns(token, spreadsheet_id, ranges) if ranges else []

    parts: dict[str, tuple[list[Tab], list[list[Any]]]] = {str(m.id): ([], []) for m in mappings}
    total = 0
    at = 0
    for (m, want, got), (cols, wanted, row_count) in zip(order, layouts, strict=True):
        read = dict(zip(wanted, columns[at : at + len(wanted)], strict=True))
        at += len(wanted)
        height = max((len(c) for c in read.values()), default=0)
        total += height
        if total > max_rows:
            raise LimitExceededError(
                "sheet_too_large",
                f"the app owner's limit is {max_rows} rows",
                extra={"limit": max_rows},
            )
        tabs, rows = parts[str(m.id)]
        start = len(rows)
        rows.extend([None] * len(m.columns) for _ in range(height))
        for i, c in enumerate(m.columns):
            for r, value in enumerate(read.get(cols[c["field"]], [])):
                rows[start + r][i] = value
        tabs.append(
            Tab(
                int(got["sheetId"]),
                got["title"],
                row_count,
                start,
                height,
                cols,
                bool(want.get("append")),
            )
        )
    return {
        mid: Sheet(tz, tabs, {c["field"]: i for i, c in enumerate(m.columns)}, rows)
        for m in mappings
        for mid, (tabs, rows) in [(str(m.id), parts[str(m.id)])]
    }


def row_print(sheet: Sheet, row: int, cols: Mapping[str, int]) -> str:
    return short_sha256(json.dumps([sheet.cell(row, c) for c in cols.values()], default=str), 24)


def locate(
    snapshot: Mapping[str, str], sheet: Sheet, cols: Mapping[str, int]
) -> dict[int, int] | None:
    """Where the rows a preview touched are now: in place, or moved as a
    whole to one other row (rows inserted or sorted above, or the row moved
    to another tab of the mapping). None when one changed or cannot be told
    apart from another."""
    where: dict[int, int] = {}
    index: dict[str, list[int]] | None = None
    for key, fingerprint in snapshot.items():
        row = int(key)
        if row_print(sheet, row, cols) == fingerprint:
            where[row] = row
            continue
        if index is None:
            index = {}
            for r in range(2, len(sheet.rows) + 2):
                index.setdefault(row_print(sheet, r, cols), []).append(r)
        found = index.get(fingerprint, [])
        if len(found) != 1:
            return None
        where[row] = found[0]
    if len(set(where.values())) != len(where):
        return None
    return where
