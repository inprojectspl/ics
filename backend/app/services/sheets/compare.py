"""Reading a linked sheet and comparing it with the app's records (ADR-0031).

`compare` is pure: given the link, the field definitions, the sheet, the
app's rows and the base it returns the plan of a sync, so every rule of the
three-way comparison is testable without Google or the broker.

The sheet carries no ids. A row is matched to a record by the link's
`key_field` when it has one; otherwise by content (a row equal to what was
last agreed, wherever it moved), then by the row it was last seen in and by
similarity. Every sync works the matching out again from the sheet as it is.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from app.domain_errors import ConflictError, LimitExceededError, NotFoundError
from app.models import SheetLink
from app.util import short_sha256

from . import google, values

# Set in the base of a record appended to the sheet until the write is
# confirmed: without a row it is appended again, not reported as removed.
UNCONFIRMED = "~unconfirmed"
# Above this many unmatched row/record pairs only exact and same-row matches
# are tried, so a reshuffled big sheet costs no quadratic scan.
_SIMILARITY_PAIRS = 250_000


def norm_header(name: Any) -> str:
    return str(name).strip().casefold()


# ---------------------------------------------------------------- the sheet


@dataclass
class Sheet:
    sheet_id: int
    title: str
    tz: str
    row_count: int
    header: dict[str, int]
    rows: list[list[Any]]
    # Headers the first row carries more than once.
    duplicates: set[str] = dataclass_field(default_factory=set)

    def cell(self, row: int, col: int) -> Any:
        """Value at 1-based sheet row `row` (row 1 is the header), 0-based column."""
        cells = self.rows[row - 2] if 2 <= row < len(self.rows) + 2 else []
        return cells[col] if col < len(cells) else None


def column_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


async def read_sheet(token: str, link: SheetLink, max_rows: int) -> Sheet:
    """The tab's header row, then only the linked columns, so a wide sheet
    costs no more than a narrow one."""
    meta = await google.spreadsheet_meta(token, link.spreadsheet_id)
    tabs = [s["properties"] for s in meta.get("sheets", [])]
    tab = next((t for t in tabs if t["title"] == link.sheet_title), None)
    if tab is None:
        raise NotFoundError(
            "sheet_tab_not_found",
            f"the spreadsheet has no tab {link.sheet_title!r}",
            extra={"tabs": [t["title"] for t in tabs][:50]},
        )
    grid = tab.get("gridProperties", {})
    row_count = int(grid.get("rowCount", 1000))
    a1 = google.a1_tab(link.sheet_title)
    last_col = column_letter(max(int(grid.get("columnCount", 26)), 1) - 1)
    first_row = await google.read_values(token, link.spreadsheet_id, f"{a1}!A1:{last_col}1")
    header: dict[str, int] = {}
    duplicates: set[str] = set()
    for i, name in enumerate(first_row[0] if first_row else []):
        key = norm_header(name)
        if key in header:
            duplicates.add(key)
        elif key:
            header[key] = i
    wanted = sorted(
        {header[k] for k in (norm_header(c["header"]) for c in link.columns) if k in header}
    )
    last_row = min(row_count, max_rows + 2)
    columns = (
        await google.read_columns(
            token,
            link.spreadsheet_id,
            [f"{a1}!{column_letter(c)}2:{column_letter(c)}{last_row}" for c in wanted],
        )
        if wanted and last_row >= 2
        else []
    )
    height = max((len(c) for c in columns), default=0)
    if height > max_rows:
        raise LimitExceededError(
            "sheet_too_large",
            f"the app owner's limit is {max_rows} rows",
            extra={"limit": max_rows},
        )
    width = (wanted[-1] + 1) if wanted else 0
    rows: list[list[Any]] = [[None] * width for _ in range(height)]
    for col, column in zip(wanted, columns, strict=True):
        for i, value in enumerate(column):
            rows[i][col] = value
    return Sheet(
        sheet_id=int(tab["sheetId"]),
        title=link.sheet_title,
        tz=str(meta.get("properties", {}).get("timeZone") or "UTC"),
        row_count=row_count,
        header=header,
        rows=rows,
        duplicates=duplicates,
    )


def layout(link: SheetLink, sheet: Sheet) -> dict[str, int]:
    """Each linked field's column; a missing or doubled header stops the sync
    rather than read the wrong column."""
    wanted = [c["header"] for c in link.columns]
    missing = [h for h in wanted if norm_header(h) not in sheet.header]
    if missing:
        raise ConflictError(
            "sheet_headers_missing",
            "the sheet's first row lacks linked headers",
            extra={"missing": missing},
        )
    doubled = [h for h in wanted if norm_header(h) in sheet.duplicates]
    if doubled:
        raise ConflictError(
            "sheet_headers_duplicate",
            "a linked header appears more than once in the sheet's first row",
            extra={"duplicates": doubled},
        )
    return {c["field"]: sheet.header[norm_header(c["header"])] for c in link.columns}


def row_print(sheet: Sheet, row: int, cols: Mapping[str, int]) -> str:
    return short_sha256(json.dumps([sheet.cell(row, c) for c in cols.values()], default=str), 24)


def locate(
    snapshot: Mapping[str, str], sheet: Sheet, cols: Mapping[str, int]
) -> dict[int, int] | None:
    """Where the rows a preview touched are now: in place, or moved as a
    whole to one other row (rows inserted or sorted above). None when one
    changed or cannot be told apart from another."""
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


# ------------------------------------------------------------ the comparison

_MISSING = object()
_BAD = object()


def _sig(data: Mapping[str, Any], fields: Iterable[str]) -> str:
    return json.dumps([data.get(f) for f in fields], default=str)


def _pair(
    rows: dict[int, dict[str, Any]],
    refs: dict[str, dict[str, Any]],
    hints: Mapping[str, int | None],
    linked: list[str],
) -> dict[int, str]:
    """Rows to records by content: equal to the record's reference values
    (what was last agreed, or the app's values for a record never synced)
    anywhere in the sheet; then the row it was last seen in, if a value
    still matches; then the most similar row, if half its values match."""
    far = 1 << 30
    paired: dict[int, str] = {}
    by_sig: dict[str, list[str]] = {}
    for rid in sorted(refs, key=lambda r: hints.get(r) or far):
        by_sig.setdefault(_sig(refs[rid], linked), []).append(rid)
    for row in sorted(rows):
        same = by_sig.get(_sig(rows[row], linked))
        if same:
            paired[row] = same.pop(0)
    taken = set(paired.values())
    free_rows = [r for r in rows if r not in paired]
    free = [rid for rid in refs if rid not in taken]

    def score(row: int, rid: str) -> int:
        return sum(1 for f in linked if rows[row].get(f) == refs[rid].get(f))

    if len(free_rows) * len(free) > _SIMILARITY_PAIRS:
        at = {hints[rid]: rid for rid in free if hints.get(rid)}
        candidates = [(0, 0, r, at[r]) for r in free_rows if r in at and score(r, at[r])]
    else:
        candidates = []
        for row in free_rows:
            for rid in free:
                n = score(row, rid)
                hint = hints.get(rid)
                if n and (2 * n >= len(linked) or hint == row):
                    candidates.append((-n, abs(row - hint) if hint else far, row, rid))
        candidates.sort()
    for _, _, row, rid in candidates:
        if row not in paired and rid not in taken:
            paired[row] = rid
            taken.add(rid)
    return paired


def compare(
    link: SheetLink,
    fields: dict[str, dict[str, Any]],
    sheet: Sheet,
    app_rows: list[dict[str, Any]],
    base: dict[str, dict[str, Any]],
    seen_at: Mapping[str, int | None] | None = None,
    required: Iterable[str] = (),
    conditions: Mapping[str, Any] | None = None,
    new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> dict[str, Any]:
    """What a sync would change; pure, so every rule is testable without I/O.

    `seen_at`: the row each record was last seen in. `conditions`: the app's
    update rule conditions on linked fields; a record that fails them cannot
    take the sheet's values, so those are reported. A new row gets its
    record's id here (`new_id`), before the app or the sheet is written."""
    cols = layout(link, sheet)
    owner = {c["field"]: c["owner"] for c in link.columns}
    linked = list(owner)
    from_sheet = [f for f, kind in owner.items() if kind != "app"]
    app = {str(r["id"]): r for r in app_rows}
    seen_at = seen_at or {}
    updates: list[dict[str, Any]] = []
    creates: list[dict[str, Any]] = []
    converged: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    touched: set[int] = set()
    required = set(required)

    # Every row with something in a linked column, parsed once.
    parsed: dict[int, dict[str, Any]] = {}
    errors: dict[int, dict[str, str]] = {}
    for row in range(2, len(sheet.rows) + 2):
        if all(sheet.cell(row, c) in (None, "") for c in cols.values()):
            continue
        parsed[row] = {}
        for field in linked:
            try:
                parsed[row][field] = values.from_cell(
                    fields[field], sheet.cell(row, cols[field]), tz=sheet.tz
                )
            except values.CellError as e:
                parsed[row][field] = _BAD
                errors.setdefault(row, {})[field] = str(e)

    def report_errors(row: int, only: Iterable[str]) -> bool:
        bad = [f for f in only if f in errors.get(row, {})]
        for f in bad:
            issues.append(
                {"kind": "invalid_value", "row": row, "field": f, "detail": errors[row][f]}
            )
        return not bad

    # Records the sheet may hold: the app's, and those agreed on before that
    # the person no longer sees (deleted in the app or hidden), so their rows
    # are never mistaken for new ones.
    refs = {rid: vals for rid, vals in base.items()}
    for rid, record in app.items():
        if rid not in refs:
            refs[rid] = {f: values.from_app(fields[f], record.get(f)) for f in linked}
    paired: dict[int, str] = {}
    if link.key_field:
        key = link.key_field
        first: dict[str, int] = {}
        doubled: set[int] = set()
        for row in sorted(parsed):
            value = parsed[row][key]
            if value is _BAD or value is None:
                continue
            text = json.dumps(value, default=str)
            if text in first:
                issues.append({"kind": "duplicate_key", "row": row, "first_row": first[text]})
                doubled.add(row)
            else:
                first[text] = row
        for rid, ref in refs.items():
            own = values.from_app(fields[key], app[rid].get(key)) if rid in app else None
            for value in (own, ref.get(key)):
                at = first.get(json.dumps(value, default=str)) if value is not None else None
                if at is not None and at not in paired:
                    paired[at] = rid
                    break
        # A row whose key no record has is a new record, like a keyless one.
        unkeyed = [r for r in sorted(parsed) if r not in paired and r not in doubled]
    else:
        paired = _pair(parsed, refs, seen_at, linked)
        unkeyed = [r for r in sorted(parsed) if r not in paired]

    def match(row: int, record_id: str) -> None:
        record = app[record_id]
        agreed = base.get(record_id, {})
        imports: dict[str, Any] = {}
        exports: dict[str, Any] = {}
        conflicts: list[dict[str, Any]] = []
        same: dict[str, Any] = {UNCONFIRMED: False} if agreed.get(UNCONFIRMED) else {}
        report_errors(row, [f for f in linked if owner[f] != "app"])
        for field, kind in owner.items():
            mine = values.from_app(fields[field], record.get(field))
            theirs = parsed[row][field]
            if theirs is _BAD:
                if kind == "app":
                    exports[field] = mine
                continue
            if mine == theirs:
                if agreed.get(field, _MISSING) != mine:
                    same[field] = mine
                continue
            if kind == "sheet":
                imports[field] = theirs
            elif kind == "app":
                exports[field] = mine
            elif field in agreed and theirs == agreed[field]:
                exports[field] = mine
            elif field in agreed and mine == agreed[field]:
                imports[field] = theirs
            else:
                conflicts.append(
                    {"field": field, "base": agreed.get(field), "app": mine, "sheet": theirs}
                )
        if (imports or conflicts) and any(
            record.get(f) != v for f, v in (conditions or {}).items()
        ):
            issues.append(
                {
                    "kind": "not_editable",
                    "row": row,
                    "record_id": record_id,
                    "fields": sorted([*imports, *(c["field"] for c in conflicts)]),
                }
            )
            imports, conflicts = {}, []
        if imports or exports or conflicts:
            updates.append(
                {
                    "record_id": record_id,
                    "row": row,
                    "revision": record["revision"],
                    "import": imports,
                    "export": exports,
                    "conflicts": conflicts,
                    "same": same,
                }
            )
            touched.add(row)
        elif same:
            converged.append({"record_id": record_id, "values": same})

    rows: dict[str, int] = {}
    for row, rid in sorted(paired.items()):
        if rid in app:
            rows[rid] = row
            match(row, rid)
        else:
            issues.append({"kind": "record_not_in_app", "row": row, "record_id": rid})

    for row in unkeyed:
        if not report_errors(row, from_sheet):
            continue
        data = {f: parsed[row][f] for f in from_sheet if parsed[row][f] is not None}
        if not data:
            issues.append({"kind": "unmatched_row", "row": row})
        elif missing := sorted(required - data.keys()):
            issues.append({"kind": "missing_required", "row": row, "fields": missing})
        else:
            creates.append({"row": row, "record_id": new_id(), "data": data})
            touched.add(row)

    appends: list[dict[str, Any]] = []
    for record_id, record in app.items():
        if record_id in rows:
            continue
        if record_id in base and not base[record_id].get(UNCONFIRMED):
            # Its row is gone from the sheet: deleting is never inferred.
            issues.append({"kind": "removed_from_sheet", "record_id": record_id})
            continue
        appends.append(
            {
                "record_id": record_id,
                "values": {f: values.from_app(fields[f], record.get(f)) for f in owner},
            }
        )

    return {
        "sheet": {"sheet_id": sheet.sheet_id, "title": sheet.title, "cols": cols},
        "updates": updates,
        "creates": creates,
        "appends": appends,
        "converged": converged,
        "issues": issues,
        # Rows of matched records not seen there at the last sync: the base
        # keeps the others' rows already.
        "rows": {rid: row for rid, row in rows.items() if seen_at.get(rid) != row},
        "snapshot": {str(r): row_print(sheet, r, cols) for r in sorted(touched)},
        "summary": {
            "imports": sum(len(u["import"]) for u in updates) + len(creates),
            "exports": sum(len(u["export"]) for u in updates) + len(appends),
            "conflicts": sum(len(u["conflicts"]) for u in updates),
            "creates": len(creates),
            "appends": len(appends),
            "issues": len(issues),
            # Records both sides already agree on whose base is not stored yet.
            "agreed": len(converged),
        },
    }
