"""Comparing the linked tabs of a file with the app's records (ADR-0031,
ADR-0033).

`compare` is pure: given the mapping, the field definitions, the sheet,
the app's rows and the base it returns the plan of a sync, so every rule of
the three-way comparison is testable without Google or the broker.

The sheet carries no ids. A row is matched to a record by the mapping's
`key_field` when it has one; otherwise by content (a row equal to what was
last agreed, wherever it moved), then by the row it was last seen in and by
similarity. Every sync works the matching out again from the sheet as it is.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from app.models import SheetMapping

from . import mapping_rules, values
from .book import Sheet, row_print

# Set in the base of a record appended to the sheet until the write is
# confirmed: without a row it is appended again, not reported as removed.
UNCONFIRMED = "~unconfirmed"
# Above this many unmatched row/record pairs only exact and same-row matches
# are tried, so a reshuffled big sheet costs no quadratic scan.
_SIMILARITY_PAIRS = 250_000


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
    mapping: SheetMapping,
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
    record's id here (`new_id`), before the app or the sheet is written.

    `tab_field` reads like a column the sheet owns whose value is the name of
    the row's tab. A mapping whose columns are all the sheet's (a list the
    app only reads) never appends rows; otherwise a record the sheet lacks
    is appended to the mapping's append tab with the columns the app owns or
    shares and the values it has for the sheet's own columns."""
    cols = sheet.cols
    owner = mapping_rules.owners(mapping)
    tab_field = mapping.tab_field
    linked = list(owner)
    from_sheet = [f for f, kind in owner.items() if kind != "app"]
    can_append = not mapping_rules.read_only(mapping.columns)
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
            raw = sheet.at(row)[0].title if field == tab_field else sheet.cell(row, cols[field])
            try:
                parsed[row][field] = values.from_cell(fields[field], raw, tz=sheet.tz)
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
    key = mapping.key_field
    if key:
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
    target = sheet.append_tab()
    for record_id, record in app.items():
        if record_id in rows:
            continue
        if record_id in base and not base[record_id].get(UNCONFIRMED):
            # Its row is gone from the sheet: deleting is never inferred.
            issues.append({"kind": "removed_from_sheet", "record_id": record_id})
            continue
        if not can_append or target is None:
            continue
        own = {f: values.from_app(fields[f], record.get(f)) for f in cols}
        if key and own.get(key) is None:
            # Without its key the row could never be told from a new one.
            issues.append({"kind": "key_missing", "record_id": record_id})
            continue
        appends.append(
            {
                "record_id": record_id,
                "sheet_id": target.sheet_id,
                "values": own,
                # A column the sheet owns gets only a value the app has: an
                # empty one would overwrite a formula or default of the sheet.
                "blank": [f for f, v in own.items() if owner[f] == "sheet" and v is None],
            }
        )

    return {
        "sheet": {"cols": cols, "tabs": [t.view() for t in sheet.tabs]},
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
