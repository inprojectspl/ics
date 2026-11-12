"""What a package brings besides code: seed rows for new collections and the
app's document view.

Seed rows (`seed/<collection>.json`, a JSON array of records) fill a
collection once, when a release creates it; they turn an existing document
into an app's data. Their structure is checked here, their values by the
broker with the rules of the app's own API (`plan._compile`). The document
view (`"document": {"endpoint": ...}`) is a read-only endpoint that renders
the app's content, records filled in, as Markdown: agents read an app
through it.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import TYPE_CHECKING, Any

from app.services.micro_applications import ddl
from app.storage import read_all, storage_from_url

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.micro_applications.manifest import Package

SEED_DIR = "seed/"
MAX_SEED_ROWS = 1000
_SEED_FILE = re.compile(r"^seed/([a-z][a-z0-9_]{0,47})\.json$")
_SEED_NS = uuid.UUID("6b1f6c9e-3f5a-4b8e-9a51-2a7f2d1c0e41")
_INSERT_BATCH = 200
# System fields a seed may carry: an imported record keeps its id and date.
SEED_SYSTEM: dict[str, dict[str, str]] = {
    "id": {"type": "uuid"},
    "created_at": {"type": "timestamptz"},
}


def document_endpoint(m: dict[str, Any]) -> dict[str, Any] | None:
    """The endpoint the manifest names as its document view, if any."""
    name = (m.get("document") or {}).get("endpoint")
    return next((e for e in m.get("endpoints", []) if e["name"] == name), None) if name else None


def check(pkg: Package, m: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Validate seed files and the document view; returns the seed rows by
    collection (only when the package is valid so far)."""
    _check_document(pkg, m)
    return _check_seeds(pkg, m)


def _check_document(pkg: Package, m: dict[str, Any]) -> None:
    from app.services.micro_applications.manifest import _PARAM

    if not m.get("document"):
        return
    ep = document_endpoint(m)
    pointer = "/document/endpoint"
    if ep is None:
        pkg.error("document_endpoint_unknown", "no endpoint with this name", pointer=pointer)
        return
    # A GET endpoint is read_only (manifest rule), so GET is the whole test.
    if ep["method"] != "GET":
        pkg.error(
            "document_endpoint_writes",
            "the document view is a GET, read_only endpoint",
            pointer=pointer,
        )
    if _PARAM.search(ep["path"]):
        pkg.error(
            "document_endpoint_params",
            "the document view takes no path parameters",
            pointer=pointer,
        )
    out = ep.get("output") or {}
    md = (out.get("properties") or {}).get("markdown") or {}
    if (
        out.get("type") != "object"
        or md.get("type") != "string"
        or "markdown" not in out.get("required", [])
    ):
        pkg.error(
            "document_output_invalid",
            'the document view returns {"markdown": string} (required)',
            pointer=pointer,
        )


def _check_seeds(pkg: Package, m: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    collections: dict[str, Any] = m["database"]["collections"]
    seeds: dict[str, list[dict[str, Any]]] = {}
    for path, raw in pkg.files.items():
        if not path.startswith(SEED_DIR):
            continue
        match = _SEED_FILE.match(path)
        if not match or match.group(1) not in collections:
            pkg.error(
                "seed_collection_unknown",
                "seed/<collection>.json for a declared collection",
                file=path,
            )
            continue
        try:
            rows = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            pkg.error("seed_not_json", f"not valid JSON: {e}", file=path)
            continue
        if not isinstance(rows, list) or len(rows) > MAX_SEED_ROWS:
            pkg.error("seed_invalid", f"a JSON array of at most {MAX_SEED_ROWS} records", file=path)
            continue
        fields = collections[match.group(1)]["fields"]
        ok = True
        for i, row in enumerate(rows):
            ok = _check_row(pkg, path, fields, row, f"/{i}") and ok
        if ok:
            seeds[match.group(1)] = rows
    return seeds


def _check_row(pkg: Package, path: str, fields: dict[str, Any], row: Any, pointer: str) -> bool:
    """The record's shape; its values go to the broker."""
    if not isinstance(row, dict):
        pkg.error("seed_row_invalid", "each record is an object", file=path, pointer=pointer)
        return False
    ok = True
    for key in row:
        if key not in SEED_SYSTEM and key not in fields:
            pkg.error(
                "seed_field_unknown",
                f"{key} is not a field (of the system fields only id and created_at)",
                file=path,
                pointer=f"{pointer}/{key}",
            )
            ok = False
    for name, f in fields.items():
        if row.get(name) is None and f.get("required") and "default" not in f:
            pkg.error(
                "seed_field_missing", f"{name} is required", file=path, pointer=f"{pointer}/{name}"
            )
            ok = False
    return ok


def seed_statements(
    schema: str,
    model: dict[str, Any],
    seeds: dict[str, list[dict[str, Any]]],
    *,
    created_by: uuid.UUID,
    plan_id: str,
) -> list[str]:
    """INSERTs for the seed rows of the collections a migration creates (the
    plan keeps only those). Row ids not given by the seed derive from the
    plan, so a retried migration repeats exactly the same statements (its
    checksum must not change)."""
    out: list[str] = []
    for coll, rows in seeds.items():
        fields = model[coll]["fields"]
        names = list(fields)
        cols = ", ".join(ddl.ident(c) for c in ["id", "created_by", "created_at", *names])
        values = []
        for i, row in enumerate(rows):
            rid = row.get("id") or str(uuid.uuid5(_SEED_NS, f"{plan_id}:{coll}:{i}"))
            at = row.get("created_at")
            cells = [
                ddl.literal(SEED_SYSTEM["id"], rid),
                ddl.literal({"type": "uuid"}, str(created_by)),
                ddl.literal(SEED_SYSTEM["created_at"], at) if at else "now()",
                *(ddl.literal(fields[n], row.get(n, fields[n].get("default"))) for n in names),
            ]
            values.append(f"({', '.join(cells)})")
        for start in range(0, len(values), _INSERT_BATCH):
            chunk = ",\n".join(values[start : start + _INSERT_BATCH])
            out.append(
                f"INSERT INTO {ddl.ident(schema)}.{ddl.ident(coll)} ({cols}) VALUES\n{chunk}"
            )
    return out


async def read_seed_rows(
    settings: Settings, version_prefix: str, collections: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Seed rows of `collections` from a stored package version: the plan
    validated them and its digest binds the bytes."""
    storage = storage_from_url(settings.storage_url)
    return {
        c: json.loads(await read_all(storage, f"{version_prefix}/{SEED_DIR}{c}.json"))
        for c in collections
    }
