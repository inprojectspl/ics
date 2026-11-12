"""Tables from the manifest data model, and the allowed changes between two
models. No SQL fragment ever comes from the manifest: identifiers pass a
strict pattern, literals are rendered from validated scalar values.

v1 accepts additive changes only: a new collection, an optional or defaulted
field, a new index. Dropping, renaming, retyping or tightening is refused at
plan time (`destructive_change`).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"unsafe identifier {name!r}")
    return f'"{name}"'


def literal(f: dict[str, Any], value: Any) -> str:
    """SQL literal of a validated value (a default or a seed row) for field `f`."""
    t = f["type"]
    if value is None:
        return "NULL"
    if t == "boolean":
        if not isinstance(value, bool):
            raise ValueError("boolean default")
        return "TRUE" if value else "FALSE"
    if t == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("integer default")
        return str(int(value))
    if t == "decimal":
        try:
            return f"'{Decimal(str(value))}'::numeric"
        except InvalidOperation as e:
            raise ValueError("decimal default") from e
    if t == "date":
        return f"'{date.fromisoformat(str(value)).isoformat()}'::date"
    text = json.dumps(value, ensure_ascii=False) if t == "json" else str(value)
    if "\x00" in text:
        raise ValueError("NUL in default")
    # standard_conforming_strings is on: only the quote needs doubling.
    quoted = "'" + text.replace("'", "''") + "'"
    if t == "timestamptz":
        return f"{quoted}::timestamptz"
    if t == "json":
        return f"{quoted}::jsonb"
    if t == "uuid":
        return f"{quoted}::uuid"
    return quoted


def _short(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:10]


def column_sql(
    schema: str, coll: str, name: str, f: dict[str, Any]
) -> tuple[str, list[str], list[str]]:
    """Column definition, its named CHECK constraints and its foreign key
    (added after every table of the change exists)."""
    col = ident(name)
    t = f["type"]
    checks: list[str] = []
    if t == "string":
        sql_type = f"varchar({int(f['maxLength'])})"
        if f.get("minLength"):
            checks.append(f"char_length({col}) >= {int(f['minLength'])}")
    elif t == "integer":
        sql_type = "bigint"
        if "minimum" in f:
            checks.append(f"{col} >= {int(f['minimum'])}")
        if "maximum" in f:
            checks.append(f"{col} <= {int(f['maximum'])}")
    elif t == "boolean":
        sql_type = "boolean"
    elif t == "decimal":
        sql_type = f"numeric({int(f['precision'])},{int(f['scale'])})"
        if "minimum" in f:
            checks.append(f"{col} >= {literal(f, f['minimum'])}")
        if "maximum" in f:
            checks.append(f"{col} <= {literal(f, f['maximum'])}")
    elif t == "date":
        sql_type = "date"
    elif t == "timestamptz":
        sql_type = "timestamptz"
    elif t == "uuid":
        sql_type = "uuid"
    elif t == "enum":
        sql_type = "text"
        values = ", ".join(literal({"type": "string"}, v) for v in f["values"])
        checks.append(f"{col} IN ({values})")
    elif t == "json":
        sql_type = "jsonb"
        checks.append(f"octet_length({col}::text) <= {int(f['maxBytes'])}")
    else:
        raise ValueError(f"unsupported type {t}")
    parts = [col, sql_type]
    if f.get("required"):
        parts.append("NOT NULL")
    if "default" in f:
        parts.append(f"DEFAULT {literal(f, f['default'])}")
    constraints = [
        f"CONSTRAINT {ident('ck_' + coll[:20] + '_' + _short(coll, name, str(i)))} CHECK ({c})"
        for i, c in enumerate(checks)
    ]
    fks: list[str] = []
    ref = f.get("references") if t == "uuid" else None
    if ref:
        fks.append(
            f"CONSTRAINT {ident('fk_' + coll[:20] + '_' + _short(coll, name, 'fk'))} "
            f"FOREIGN KEY ({col}) REFERENCES {ident(schema)}.{ident(ref['collection'])} (id) "
            "ON DELETE RESTRICT"
        )
    return " ".join(parts), constraints, fks


def create_table_sql(schema: str, coll: str, model: dict[str, Any]) -> tuple[list[str], list[str]]:
    cols = [
        "id uuid PRIMARY KEY",
        "created_by uuid NOT NULL",
        "created_at timestamptz NOT NULL DEFAULT now()",
        "updated_at timestamptz NOT NULL DEFAULT now()",
        "revision integer NOT NULL DEFAULT 1 CHECK (revision > 0)",
    ]
    constraints: list[str] = []
    fks: list[str] = []
    for name, f in model["fields"].items():
        c, extra, fk = column_sql(schema, coll, name, f)
        cols.append(c)
        constraints.extend(extra)
        fks.extend(f"ALTER TABLE {ident(schema)}.{ident(coll)} ADD {x}" for x in fk)
    stmts = [f"CREATE TABLE {ident(schema)}.{ident(coll)} ({', '.join(cols + constraints)})"]
    stmts.extend(index_sql(schema, coll, idx) for idx in model.get("indexes", []))
    return stmts, fks


def index_sql(schema: str, coll: str, idx: dict[str, Any]) -> str:
    fields = idx["fields"]
    name = ident(f"ix_{coll[:20]}_{_short(coll, *fields, str(bool(idx.get('unique'))))}")
    unique = "UNIQUE " if idx.get("unique") else ""
    cols = ", ".join(ident(f) for f in fields)
    return f"CREATE {unique}INDEX {name} ON {ident(schema)}.{ident(coll)} ({cols})"


SYSTEM_TABLES = (
    'CREATE TABLE {s}."_ics_idempotency" ('
    "data_generation integer NOT NULL, actor uuid NOT NULL, route text NOT NULL, "
    "key text NOT NULL, request_hash text NOT NULL, release_id text, status integer, "
    "response jsonb, headers jsonb, created_at timestamptz NOT NULL DEFAULT now(), "
    "PRIMARY KEY (data_generation, actor, route, key))",
    'CREATE TABLE {s}."_ics_audit" ('
    "id uuid PRIMARY KEY DEFAULT gen_random_uuid(), at timestamptz NOT NULL DEFAULT now(), "
    "actor uuid NOT NULL, action text NOT NULL, collection text NOT NULL, record_id uuid, "
    "request_id text, release_id text, details jsonb)",
    'CREATE TABLE {s}."_ics_schema_migrations" ('
    "version integer PRIMARY KEY, checksum text NOT NULL, operation_id text, "
    "statements jsonb NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())",
)


@dataclass
class Delta:
    collections_added: list[str] = field(default_factory=list)
    fields_added: list[str] = field(default_factory=list)
    indexes_added: list[str] = field(default_factory=list)
    destructive: list[dict[str, str]] = field(default_factory=list)
    statements: list[str] = field(default_factory=list)

    @property
    def changes_schema(self) -> bool:
        return bool(self.statements)

    def as_dict(self) -> dict[str, Any]:
        return {
            "collections_added": self.collections_added,
            "fields_added": self.fields_added,
            "indexes_added": self.indexes_added,
            "destructive": self.destructive,
            "statement_count": len(self.statements),
        }


def diff(schema: str, old: dict[str, Any], new: dict[str, Any]) -> Delta:
    delta = Delta()
    late: list[str] = []
    for coll in old:
        if coll not in new:
            delta.destructive.append(
                {
                    "pointer": f"/database/collections/{coll}",
                    "reason": "collections cannot be removed in v1",
                }
            )
    for coll, model in new.items():
        if coll not in old:
            delta.collections_added.append(coll)
            stmts, fks = create_table_sql(schema, coll, model)
            delta.statements.extend(stmts)
            late.extend(fks)
            continue
        before = old[coll]
        for fname, f in before["fields"].items():
            if fname not in model["fields"]:
                delta.destructive.append(
                    {
                        "pointer": f"/database/collections/{coll}/fields/{fname}",
                        "reason": "fields cannot be removed in v1",
                    }
                )
            elif _canon(model["fields"][fname]) != _canon(f):
                delta.destructive.append(
                    {
                        "pointer": f"/database/collections/{coll}/fields/{fname}",
                        "reason": "a field's type and constraints cannot change in v1",
                    }
                )
        for fname, f in model["fields"].items():
            if fname in before["fields"]:
                continue
            if f.get("required") and "default" not in f:
                delta.destructive.append(
                    {
                        "pointer": f"/database/collections/{coll}/fields/{fname}",
                        "reason": "a new required field needs a default (no backfill in v1)",
                    }
                )
                continue
            col, constraints, fks = column_sql(schema, coll, fname, f)
            delta.fields_added.append(f"{coll}.{fname}")
            delta.statements.append(f"ALTER TABLE {ident(schema)}.{ident(coll)} ADD COLUMN {col}")
            delta.statements.extend(
                f"ALTER TABLE {ident(schema)}.{ident(coll)} ADD {c}" for c in constraints
            )
            late.extend(f"ALTER TABLE {ident(schema)}.{ident(coll)} ADD {x}" for x in fks)
        old_idx = {_canon(i) for i in before.get("indexes", [])}
        new_idx = {_canon(i) for i in model.get("indexes", [])}
        for gone in old_idx - new_idx:
            delta.destructive.append(
                {
                    "pointer": f"/database/collections/{coll}/indexes",
                    "reason": f"index {gone} cannot be removed in v1",
                }
            )
        for idx in model.get("indexes", []):
            if _canon(idx) not in old_idx:
                delta.indexes_added.append(f"{coll}({', '.join(idx['fields'])})")
                delta.statements.append(index_sql(schema, coll, idx))
    delta.statements.extend(late)
    return delta


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def checksum(statements: list[str]) -> str:
    return hashlib.sha256("\n".join(statements).encode()).hexdigest()
