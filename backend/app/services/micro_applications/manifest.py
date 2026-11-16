"""Package and manifest validation for `ics.microapp/v1alpha1`.

Two stages, as the contract describes: the JSON Schema (draft 2020-12) checks
structure, then a bounded semantic pass checks references, consistency and
platform limits. Every problem is reported with `file`, `pointer` and a
stable `code` so an agent can fix it without guessing.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from app.services.micro_applications.package import check_paths

CONTRACT_VERSION = "ics.microapp/v1alpha1"
PROFILE = "js-capabilities-v1"
SDK_VERSION = "1.0"
# Part of every plan digest: a validator change invalidates older plans.
VALIDATOR_VERSION = "2026-11-12.1"
MANIFEST_PATH = "microapp.json"

# Platform limits of the v1alpha1 contract; a manifest may request less, never more.
LIMITS: dict[str, int] = {
    "max_files": 50,
    "max_package_bytes": 5 * 1024 * 1024,
    "max_handler_bytes": 256 * 1024,
    "max_collections": 20,
    "max_fields_per_collection": 40,
    "max_indexes_per_collection": 8,
    "max_endpoints": 30,
    "max_json_field_bytes": 65536,
    "max_string_length": 100_000,
    "max_decimal_precision": 38,
    "wall_ms": 5000,
    "max_db_calls": 20,
    "max_response_bytes": 262_144,
    "js_cpu_ms": 250,
    "guest_heap_bytes": 32 * 1024 * 1024,
    "min_idle_seconds": 60,
    "max_idle_seconds": 3600,
}

SYSTEM_FIELDS = ("id", "created_by", "created_at", "updated_at", "revision")
READ_OPERATIONS = frozenset({"get", "list", "count", "groupCount"})
_PARAM = re.compile(r":([a-z][a-z0-9_]{0,47})")


@dataclass(frozen=True)
class Diagnostic:
    code: str
    message: str
    file: str = MANIFEST_PATH
    pointer: str = ""
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "file": self.file,
            "pointer": self.pointer or "/",
            "severity": self.severity,
        }


@dataclass
class Package:
    files: dict[str, bytes]
    manifest: dict[str, Any] | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    # Seed rows by collection (`seed/<collection>.json`), once validated.
    seeds: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Values the manifest states for fields (defaults, conditions, allowed
    # values) as `{pointer, code, field, value}`, `field` the field's pointer:
    # checked by the broker with the rules of the app's own API.
    values: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)

    def error(
        self, code: str, message: str, *, file: str = MANIFEST_PATH, pointer: str = ""
    ) -> None:
        self.diagnostics.append(Diagnostic(code, message, file, pointer))

    def warn(
        self, code: str, message: str, *, file: str = MANIFEST_PATH, pointer: str = ""
    ) -> None:
        self.diagnostics.append(Diagnostic(code, message, file, pointer, "warning"))

    @property
    def total_bytes(self) -> int:
        return sum(len(b) for b in self.files.values())

    def file_entries(self) -> list[dict[str, Any]]:
        return [
            {"path": p, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}
            for p, b in sorted(self.files.items())
        ]


@lru_cache
def manifest_schema() -> dict[str, Any]:
    return json.loads((Path(__file__).with_name("manifest.schema.json")).read_text())


def _validator() -> Draft202012Validator:
    return Draft202012Validator(manifest_schema(), format_checker=FormatChecker())


def _pointer(parts: Any) -> str:
    return "".join(f"/{str(p).replace('~', '~0').replace('/', '~1')}" for p in parts)


def load_package(raw_files: list[tuple[str, bytes]]) -> Package:
    """Validate a complete package. `manifest` is set only when it parsed."""
    pkg = Package(files={})
    check_paths(pkg, raw_files)
    if MANIFEST_PATH not in pkg.files:
        pkg.error("manifest_missing", "the package has no microapp.json", file="")
        return pkg
    try:
        manifest = json.loads(pkg.files[MANIFEST_PATH].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        pkg.error("manifest_not_json", f"microapp.json is not valid JSON: {e}")
        return pkg
    errors = sorted(_validator().iter_errors(manifest), key=lambda e: list(e.absolute_path))
    for err in errors[:50]:
        pkg.error("manifest_schema", err.message[:300], pointer=_pointer(err.absolute_path))
    if errors:
        return pkg
    pkg.manifest = manifest
    _semantic(pkg, manifest)
    from app.services.micro_applications import content

    pkg.seeds = content.check(pkg, manifest)
    return pkg


def _semantic(pkg: Package, m: dict[str, Any]) -> None:
    collections: dict[str, Any] = m["database"]["collections"]
    if len(collections) > LIMITS["max_collections"]:
        pkg.error(
            "too_many_collections",
            f"at most {LIMITS['max_collections']} collections",
            pointer="/database/collections",
        )
    permissions = set(m["permissions"])

    def need_permission(perm: str, pointer: str) -> None:
        if perm not in permissions:
            pkg.error(
                "permission_not_declared",
                f"{perm} is not declared in permissions",
                pointer=pointer,
            )

    for perm in sorted(permissions):
        if perm.startswith("app."):
            pkg.error(
                "permission_reserved",
                "app.* permissions belong to the platform",
                pointer=f"/permissions/{perm}",
            )
    in_roles: set[str] = set()
    for name, role in m["roles"].items():
        for i, perm in enumerate(role["permissions"]):
            need_permission(perm, f"/roles/{name}/permissions/{i}")
        in_roles.update(role["permissions"])
    # Access is given by role: a permission no role holds could only be
    # handed out one by one, which is what roles are there to avoid.
    for perm in sorted(permissions - in_roles):
        pkg.error(
            "permission_without_role",
            f"{perm} belongs to no role; add it to the role of the people who need it",
            pointer=f"/permissions/{perm}",
        )

    def field_known(coll: str, name: str, pointer: str, *, system_ok: bool = True) -> bool:
        if name in SYSTEM_FIELDS:
            if not system_ok:
                pkg.error(
                    "system_field_not_writable", f"{name} is set by the platform", pointer=pointer
                )
                return False
            return True
        if name not in collections.get(coll, {}).get("fields", {}):
            pkg.error("field_unknown", f"{coll}.{name} does not exist", pointer=pointer)
            return False
        return True

    for cname, coll in collections.items():
        base = f"/database/collections/{cname}"
        if cname.startswith("_ics_") or cname in ("pg", "information_schema"):
            pkg.error("collection_reserved", "reserved collection name", pointer=base)
        fields = coll["fields"]
        if len(fields) > LIMITS["max_fields_per_collection"]:
            pkg.error("too_many_fields", "too many fields", pointer=f"{base}/fields")
        for fname, f in fields.items():
            fp = f"{base}/fields/{fname}"
            if fname in SYSTEM_FIELDS or fname.startswith("_"):
                pkg.error("field_reserved", f"{fname} is a reserved field name", pointer=fp)
            _check_field(pkg, collections, f, fp)
        for op, rule in coll["crud"].items():
            rp = f"{base}/crud/{op}"
            need_permission(rule["permission"], f"{rp}/permission")
            for i, wf in enumerate(rule.get("writeFields", [])):
                field_known(cname, wf, f"{rp}/writeFields/{i}", system_ok=False)
            for i, rf in enumerate(rule.get("readFields", [])):
                field_known(cname, rf, f"{rp}/readFields/{i}")
            for cf, value in rule.get("conditions", {}).items():
                if field_known(cname, cf, f"{rp}/conditions/{cf}"):
                    _check_condition_value(pkg, fields, base, cf, value, f"{rp}/conditions/{cf}")
            for af, values in rule.get("allowedValues", {}).items():
                if af not in rule.get("writeFields", []):
                    pkg.error(
                        "allowed_values_not_writable",
                        f"{af} is not in writeFields",
                        pointer=f"{rp}/allowedValues/{af}",
                    )
                for v in values:
                    _check_condition_value(pkg, fields, base, af, v, f"{rp}/allowedValues/{af}")
            if op == "create":
                for fname, f in fields.items():
                    if (
                        f.get("required")
                        and "default" not in f
                        and fname not in rule.get("writeFields", [])
                    ):
                        pkg.error(
                            "required_field_not_writable",
                            f"{fname} is required but create cannot set it",
                            pointer=f"{rp}/writeFields",
                        )
        if len(coll.get("indexes", [])) > LIMITS["max_indexes_per_collection"]:
            pkg.error("too_many_indexes", "too many indexes", pointer=f"{base}/indexes")
        for i, idx in enumerate(coll.get("indexes", [])):
            for j, f in enumerate(idx["fields"]):
                ip = f"{base}/indexes/{i}/fields/{j}"
                if field_known(cname, f, ip) and fields.get(f, {}).get("type") == "json":
                    pkg.error("index_json_field", "JSON fields cannot be indexed", pointer=ip)

    capabilities: dict[str, Any] = m["capabilities"]
    for name, cap in capabilities.items():
        cp = f"/capabilities/{name}"
        coll = cap["collection"]
        if coll not in collections:
            pkg.error(
                "collection_unknown", f"{coll} is not a collection", pointer=f"{cp}/collection"
            )
            continue
        need_permission(cap["permission"], f"{cp}/permission")
        for key in ("readFields", "returnFields"):
            for i, f in enumerate(cap.get(key, [])):
                field_known(coll, f, f"{cp}/{key}/{i}")
        for i, f in enumerate(cap.get("writeFields", [])):
            field_known(coll, f, f"{cp}/writeFields/{i}", system_ok=False)
        fields = collections[coll]["fields"]
        base = f"/database/collections/{coll}"
        for cf, value in cap.get("conditions", {}).items():
            if field_known(coll, cf, f"{cp}/conditions/{cf}"):
                _check_condition_value(pkg, fields, base, cf, value, f"{cp}/conditions/{cf}")
        for af, values in cap.get("allowedValues", {}).items():
            if af not in cap.get("writeFields", []):
                pkg.error(
                    "allowed_values_not_writable",
                    f"{af} is not in writeFields",
                    pointer=f"{cp}/allowedValues/{af}",
                )
            for v in values:
                _check_condition_value(pkg, fields, base, af, v, f"{cp}/allowedValues/{af}")

    endpoints = m["endpoints"]
    if len(endpoints) > LIMITS["max_endpoints"]:
        pkg.error("too_many_endpoints", "too many endpoints", pointer="/endpoints")
    names: set[str] = set()
    routes: set[tuple[str, str]] = set()
    for i, ep in enumerate(endpoints):
        ep_p = f"/endpoints/{i}"
        if ep["name"] in names:
            pkg.error("endpoint_name_duplicate", "duplicate endpoint name", pointer=f"{ep_p}/name")
        names.add(ep["name"])
        shape = (ep["method"], _PARAM.sub(":", ep["path"]))
        if shape in routes:
            pkg.error(
                "route_duplicate", "two endpoints match the same requests", pointer=f"{ep_p}/path"
            )
        routes.add(shape)
        need_permission(ep["permission"], f"{ep_p}/permission")
        handler_file = ep["handler"].split("#", 1)[0]
        if handler_file not in pkg.files:
            pkg.error(
                "handler_missing",
                f"{handler_file} is not in the package",
                pointer=f"{ep_p}/handler",
            )
        elif re.search(rb"^\s*import\s|\bimport\s*\(", pkg.files[handler_file], re.MULTILINE):
            pkg.error(
                "handler_import",
                "handlers cannot import modules in js-capabilities-v1",
                file=handler_file,
            )
        if ep["method"] == "GET" and ep["transaction"] != "read_only":
            pkg.error(
                "get_must_be_read_only",
                "GET endpoints use transaction=read_only",
                pointer=f"{ep_p}/transaction",
            )
        if ep["transaction"] == "read_only" and (
            ep["ifMatch"] != "none" or ep["idempotency"] != "none"
        ):
            pkg.error(
                "read_only_preconditions",
                "read-only endpoints take no If-Match or Idempotency-Key",
                pointer=ep_p,
            )
        for j, cname in enumerate(ep["capabilities"]):
            cap = capabilities.get(cname)
            if cap is None:
                pkg.error(
                    "capability_unknown",
                    f"{cname} is not declared",
                    pointer=f"{ep_p}/capabilities/{j}",
                )
            elif ep["transaction"] == "read_only" and cap["operation"] not in READ_OPERATIONS:
                pkg.error(
                    "read_only_write_capability",
                    "a read-only endpoint may resolve only read capabilities",
                    pointer=f"{ep_p}/capabilities/{j}",
                )
        params = set(_PARAM.findall(ep["path"]))
        schema = ep["input"].get("params")
        declared = set((schema or {}).get("properties", {}))
        if params != declared:
            pkg.error(
                "params_mismatch",
                "input.params must declare exactly the path parameters",
                pointer=f"{ep_p}/input/params",
            )
        if schema is not None and set(schema.get("required", [])) != params:
            pkg.error(
                "params_required",
                "every path parameter is required",
                pointer=f"{ep_p}/input/params/required",
            )
        if ep["method"] == "GET" and "body" in ep["input"]:
            pkg.error("get_with_body", "GET endpoints take no body", pointer=f"{ep_p}/input/body")
        for key in ("params", "query", "body"):
            if key in ep["input"]:
                _check_restricted(pkg, ep["input"][key], f"{ep_p}/input/{key}", 0)
        _check_restricted(pkg, ep["output"], f"{ep_p}/output", 0)

    entry = m["frontend"]["entry"]
    if entry not in pkg.files:
        pkg.error(
            "frontend_entry_missing", f"{entry} is not in the package", pointer="/frontend/entry"
        )
    referenced = {ep["handler"].split("#", 1)[0] for ep in endpoints}
    for p in pkg.files:
        if p.startswith("handlers/") and p not in referenced:
            pkg.warn("handler_unused", "no endpoint uses this handler", file=p)

    comp = m["compatibility"]
    if comp["schemaMin"] > comp["schemaMax"]:
        pkg.error("compatibility_range", "schemaMin must be <= schemaMax", pointer="/compatibility")
    lim = m["limitsRequested"]
    for key, platform in (
        ("wallMs", "wall_ms"),
        ("maxDbCalls", "max_db_calls"),
        ("maxResponseBytes", "max_response_bytes"),
    ):
        if lim[key] > LIMITS[platform]:
            pkg.error(
                "limit_above_platform",
                f"{key} may lower the platform limit {LIMITS[platform]}, not raise it",
                pointer=f"/limitsRequested/{key}",
            )
    idle = m["runtime"]["idleSeconds"]
    if not LIMITS["min_idle_seconds"] <= idle <= LIMITS["max_idle_seconds"]:
        pkg.error(
            "idle_out_of_range",
            f"idleSeconds must be {LIMITS['min_idle_seconds']}..{LIMITS['max_idle_seconds']}",
            pointer="/runtime/idleSeconds",
        )


def _check_field(pkg: Package, collections: dict[str, Any], f: dict[str, Any], fp: str) -> None:
    if f.get("default") is not None:
        pkg.values.append(
            {
                "pointer": f"{fp}/default",
                "code": "default_invalid",
                "field": fp,
                "value": f["default"],
            }
        )
    t = f["type"]
    if t == "string":
        if f["maxLength"] > LIMITS["max_string_length"]:
            pkg.error("string_too_long", "maxLength above the platform limit", pointer=fp)
        if f.get("minLength", 0) > f["maxLength"]:
            pkg.error("range_order", "minLength must be <= maxLength", pointer=fp)
    elif t == "integer":
        lo, hi = f.get("minimum"), f.get("maximum")
        if lo is not None and hi is not None and lo > hi:
            pkg.error("range_order", "minimum must be <= maximum", pointer=fp)
        for bound in (lo, hi):
            if bound is not None and abs(bound) > 2**53 - 1:
                pkg.error("unsafe_integer", "integers stay within ±(2^53-1)", pointer=fp)
    elif t == "decimal":
        if f["scale"] > f["precision"] or f["precision"] > LIMITS["max_decimal_precision"]:
            pkg.error("decimal_precision", "scale <= precision <= 38", pointer=fp)
    elif t == "json":
        if f["maxBytes"] > LIMITS["max_json_field_bytes"]:
            pkg.error("json_too_large", "maxBytes above the platform limit", pointer=fp)
        if f.get("required"):
            pkg.error("json_required", "JSON fields cannot be required in v1", pointer=fp)
    elif t == "uuid":
        ref = f.get("references")
        if ref and ref["collection"] not in collections:
            pkg.error(
                "reference_unknown",
                "referenced collection does not exist",
                pointer=f"{fp}/references",
            )


def _check_condition_value(
    pkg: Package, fields: dict[str, Any], base: str, name: str, value: Any, pointer: str
) -> None:
    """A condition or allowed value of field `name` (of the collection at
    `base`): its value goes to the broker (`Package.values`); JSON fields
    take none, and system fields are not checked."""
    f = fields.get(name)
    if f is None:
        return
    if f["type"] == "json":
        pkg.error("condition_value_invalid", "JSON fields take no conditions", pointer=pointer)
    elif value is not None:
        pkg.values.append(
            {
                "pointer": pointer,
                "code": "condition_value_invalid",
                "field": f"{base}/fields/{name}",
                "value": value,
            }
        )


_MAX_SCHEMA_DEPTH = 8


def _check_restricted(pkg: Package, schema: dict[str, Any], pointer: str, depth: int) -> None:
    if depth > _MAX_SCHEMA_DEPTH:
        pkg.error(
            "schema_too_deep", f"schemas nest at most {_MAX_SCHEMA_DEPTH} levels", pointer=pointer
        )
        return
    t = schema.get("type")
    if t == "object":
        props = schema.get("properties", {})
        missing = set(schema.get("required", [])) - set(props)
        if missing:
            pkg.error(
                "required_unknown",
                f"required names unknown properties: {sorted(missing)}",
                pointer=f"{pointer}/required",
            )
        for k, sub in props.items():
            _check_restricted(pkg, sub, f"{pointer}/properties/{k}", depth + 1)
    elif t == "array":
        if schema.get("minItems", 0) > schema["maxItems"]:
            pkg.error("range_order", "minItems must be <= maxItems", pointer=pointer)
        _check_restricted(pkg, schema["items"], f"{pointer}/items", depth + 1)


def data_model(manifest: dict[str, Any]) -> dict[str, Any]:
    """The part of the manifest that shapes tables: fields and indexes only."""
    return {
        name: {"fields": c["fields"], "indexes": c.get("indexes", [])}
        for name, c in manifest["database"]["collections"].items()
    }
