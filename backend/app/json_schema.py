"""A small JSON Schema subset for doc type `properties` (ADR-0015).

Doc types need only flat, typed fields, so no `jsonschema` dependency.
`check_schema` refuses keywords outside the subset (`_KEYWORDS`) so an admin never
saves a rule that would be silently ignored.
"""

from __future__ import annotations

import re
from typing import Any

_TYPES = frozenset({"object", "array", "string", "number", "integer", "boolean", "null"})
_ANNOTATIONS = frozenset({"title", "description", "default", "format", "examples", "$schema"})
_COUNTS = frozenset({"minLength", "maxLength", "minItems", "maxItems"})
_BOUNDS = frozenset({"minimum", "maximum"})
_KEYWORDS = (
    _ANNOTATIONS
    | _COUNTS
    | _BOUNDS
    | {"type", "properties", "required", "additionalProperties", "items", "enum", "const"}
    | {"pattern"}
)


class SchemaError(ValueError):
    """The schema itself is not in the supported subset."""


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def check_schema(schema: Any, path: str = "") -> None:
    """Raise `SchemaError` naming the offending location."""
    where = path or "schema"
    if not isinstance(schema, dict):
        raise SchemaError(f"{where}: must be an object")
    unknown = sorted(set(schema) - _KEYWORDS)
    if unknown:
        raise SchemaError(f"{where}: unsupported keyword {unknown[0]!r}")
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        if not names or any(n not in _TYPES for n in names):
            raise SchemaError(f"{where}.type: unknown type")
    for key in _COUNTS:
        if key in schema and (not isinstance(schema[key], int) or schema[key] < 0):
            raise SchemaError(f"{where}.{key}: must be a non-negative integer")
    for key in _BOUNDS:
        if key in schema and not _is_number(schema[key]):
            raise SchemaError(f"{where}.{key}: must be a number")
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError):
            raise SchemaError(f"{where}.pattern: invalid regular expression") from None
    if "enum" in schema and (not isinstance(schema["enum"], list) or not schema["enum"]):
        raise SchemaError(f"{where}.enum: must be a non-empty list")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(r, str) for r in required):
        raise SchemaError(f"{where}.required: must be a list of names")
    props = schema.get("properties", {})
    if not isinstance(props, dict):
        raise SchemaError(f"{where}.properties: must be an object")
    for name, sub in props.items():
        check_schema(sub, f"{where}.properties.{name}")
    extra = schema.get("additionalProperties", True)
    if not isinstance(extra, bool):
        check_schema(extra, f"{where}.additionalProperties")
    if "items" in schema:
        check_schema(schema["items"], f"{where}.items")


def _type_matches(value: Any, name: str) -> bool:
    match name:
        case "object":
            return isinstance(value, dict)
        case "array":
            return isinstance(value, list)
        case "string":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return _is_number(value)
        case "boolean":
            return isinstance(value, bool)
        case _:
            return value is None


def first_error(schema: dict[str, Any], value: Any, path: str) -> str | None:
    """Path of the first violation, or `None` when `value` is valid. The
    schema must have passed `check_schema`."""
    types = schema.get("type")
    if types is not None:
        names = types if isinstance(types, list) else [types]
        if not any(_type_matches(value, n) for n in names):
            return path
    if "enum" in schema and value not in schema["enum"]:
        return path
    if "const" in schema and value != schema["const"]:
        return path
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
            "maxLength", len(value)
        ):
            return path
        if "pattern" in schema and not re.search(schema["pattern"], value):
            return path
    if _is_number(value) and (
        value < schema.get("minimum", value) or value > schema.get("maximum", value)
    ):
        return path
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get(
            "maxItems", len(value)
        ):
            return path
        if "items" in schema:
            for i, item in enumerate(value):
                if err := first_error(schema["items"], item, f"{path}[{i}]"):
                    return err
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                return f"{path}.{name}"
        extra = schema.get("additionalProperties", True)
        for name, item in value.items():
            sub = props.get(name)
            if sub is None:
                if extra is False:
                    return f"{path}.{name}"
                sub = extra if isinstance(extra, dict) else None
            if sub is not None and (err := first_error(sub, item, f"{path}.{name}")):
                return err
    return None
