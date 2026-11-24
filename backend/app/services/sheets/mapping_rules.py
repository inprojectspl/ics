"""The rules a mapping of a collection to tabs must meet, checked against
the app's active release before a link is saved (ADR-0031, ADR-0033)."""

from __future__ import annotations

from typing import Any

from app.domain_errors import InvalidInputError
from app.models import SheetMapping

from . import values
from .book import norm_header


def linked(columns: list[dict[str, Any]], tab_field: str | None) -> dict[str, tuple[str, str]]:
    """Every field a mapping links, with its normalized header and owner. The
    tab field reads like a column the sheet owns, with no header."""
    out = {c["field"]: (norm_header(c["header"]), c["owner"]) for c in columns}
    if tab_field:
        out[tab_field] = ("", "sheet")
    return out


def owners(mapping: SheetMapping) -> dict[str, str]:
    return {f: owner for f, (_, owner) in linked(mapping.columns, mapping.tab_field).items()}


def read_only(columns: list[dict[str, Any]]) -> bool:
    """Every column is the sheet's: the app only reads the tabs and never
    writes to them, not even new rows."""
    return all(c["owner"] == "sheet" for c in columns)


def collection_def(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    collections = (manifest.get("database") or {}).get("collections") or {}
    if name not in collections:
        raise InvalidInputError(
            "collection_not_found",
            "the active release has no such collection",
            field="collection",
            extra={"choices": sorted(collections)},
        )
    collection: dict[str, Any] = collections[name]
    return collection


def update_rule(collection: dict[str, Any]) -> dict[str, Any]:
    rule: dict[str, Any] = (collection.get("crud") or {}).get("update") or {}
    return rule


def check_columns(
    collection: dict[str, Any], columns: list[dict[str, Any]], key_field: str | None
) -> None:
    """The rules the active release decides; shapes and lengths are the API model's."""
    fields = collection.get("fields") or {}
    if not columns:
        raise InvalidInputError("columns_invalid", "link at least one column", field="columns")
    seen_fields: set[str] = set()
    seen_headers: set[str] = set()
    writable = update_rule(collection).get("writeFields")
    for i, col in enumerate(columns):
        field, header, where = col["field"], col["header"], f"columns/{i}"
        if field not in fields:
            raise InvalidInputError("field_not_found", f"unknown field {field!r}", field=where)
        if fields[field]["type"] not in values.SUPPORTED:
            raise InvalidInputError(
                "field_type_unsupported",
                f"{fields[field]['type']} fields cannot be linked",
                field=where,
            )
        if not header:
            raise InvalidInputError("header_invalid", "a header of 1..100 characters", field=where)
        if field in seen_fields or norm_header(header) in seen_headers:
            raise InvalidInputError("column_duplicate", "each field and header once", field=where)
        if col["owner"] != "app" and writable is not None and field not in writable:
            raise InvalidInputError(
                "field_not_writable",
                f"the app's update rule does not let {field!r} change; make it owned by the app",
                field=where,
            )
        seen_fields.add(field)
        seen_headers.add(norm_header(header))
    if key_field is not None and key_field not in seen_fields:
        raise InvalidInputError(
            "key_field_invalid", "the key field must be one of the linked fields", field="key_field"
        )


MAX_MAPPINGS = 20
MAX_TABS = 50


def tab_ref(value: Any) -> dict[str, Any]:
    if isinstance(value, int) and not isinstance(value, bool):
        return {"sheet_id": value, "title": None}
    title = str(value).strip()
    if not title or len(title) > 100:
        raise InvalidInputError("sheet_title_invalid", "a tab name of 1..100 characters")
    return {"sheet_id": None, "title": title}


def same_tab(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a["sheet_id"] is not None and b["sheet_id"] is not None:
        return bool(a["sheet_id"] == b["sheet_id"])
    return a["title"] is not None and a["title"] == b["title"]


def mapping_tabs(
    spec: dict[str, Any], old: SheetMapping | None, where: str, can_append: bool
) -> list[dict[str, Any]]:
    """The mapping's tabs, each keeping the id an earlier read pinned for it,
    so a tab renamed since stays the same tab."""
    tabs: list[dict[str, Any]] = []
    for i, raw in enumerate(spec["tabs"]):
        tab = tab_ref(raw)
        if any(same_tab(tab, t) for t in tabs):
            raise InvalidInputError("tab_duplicate", "each tab once", field=f"{where}/tabs/{i}")
        known = next((t for t in (old.tabs if old else []) if same_tab(tab, t)), None)
        if known:
            tab = {"sheet_id": known["sheet_id"], "title": known["title"] or tab["title"]}
        tabs.append(tab)
    if not tabs or len(tabs) > MAX_TABS:
        raise InvalidInputError("tabs_invalid", f"link 1..{MAX_TABS} tabs", field=f"{where}/tabs")
    target = spec.get("append_to")
    if target is not None:
        ref = tab_ref(target)
        hit = next((t for t in tabs if same_tab(ref, t)), None)
        if hit is None:
            raise InvalidInputError(
                "append_tab_invalid",
                "new records go to one of the mapping's tabs",
                field=f"{where}/append_to",
            )
        hit["append"] = True
    elif len(tabs) > 1 and can_append:
        raise InvalidInputError(
            "append_tab_required",
            "with several tabs, name the tab new records go to",
            field=f"{where}/append_to",
        )
    return tabs


def mapping_spec(
    manifest: dict[str, Any], spec: dict[str, Any], old: SheetMapping | None, where: str
) -> dict[str, Any]:
    collection = collection_def(manifest, spec["collection"])
    key_field = spec.get("key_field") or None
    tab_field = spec.get("tab_field") or None
    columns = [
        {"field": c["field"], "header": c["header"].strip(), "owner": c["owner"]}
        for c in spec["columns"]
    ]
    check_columns(collection, columns, key_field)
    tabs = mapping_tabs(spec, old, where, not read_only(columns))
    if len(tabs) > 1 and key_field is None:
        raise InvalidInputError(
            "key_field_required",
            "rows of several tabs are matched by a key field unique across them",
            field=f"{where}/key_field",
        )
    if tab_field is not None:
        fields = collection.get("fields") or {}
        writable = update_rule(collection).get("writeFields")
        if (fields.get(tab_field) or {}).get("type") != "string":
            raise InvalidInputError(
                "tab_field_invalid", "the tab field is a string field", field=f"{where}/tab_field"
            )
        if any(c["field"] == tab_field for c in columns):
            raise InvalidInputError(
                "tab_field_invalid",
                "the tab field is not one of the linked columns",
                field=f"{where}/tab_field",
            )
        if writable is not None and tab_field not in writable:
            raise InvalidInputError(
                "field_not_writable",
                f"the app's update rule does not let {tab_field!r} change",
                field=f"{where}/tab_field",
            )
    return {
        "collection": spec["collection"],
        "tabs": tabs,
        "key_field": key_field,
        "tab_field": tab_field,
        "columns": columns,
    }
