"""Cell <-> field values.

`from_cell` turns a raw Sheets value (UNFORMATTED_VALUE, dates as serial
numbers) into the JSON value the app's field takes, `from_app` normalizes
what the broker returns, and both meet as the same canonical value, so a
number typed in the sheet equals the same number stored by the app.
`to_cell` writes typed cells: text is always a string value, never a
formula, whatever it starts with.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Sheets counts days from 1899-12-30.
_EPOCH = datetime(1899, 12, 30)
# Day first with dots only (31.12.2026); a slash date may be month first.
_DMY = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_GROUPED = re.compile(r"^-?\d{1,3}(,\d{3})+$")
SUPPORTED = ("string", "integer", "boolean", "decimal", "date", "timestamptz", "uuid", "enum")
_TRUE = {"true", "1", "yes", "tak"}
_FALSE = {"false", "0", "no", "nie"}


class CellError(ValueError):
    """The cell holds something the field cannot take."""


def _number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise CellError("not a number")
    if isinstance(value, int | float):
        return Decimal(str(value))
    text = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if "," in text:
        # A decimal comma only when nothing else can read it: "12,5" yes;
        # "1,000" or "1.234,5" may be thousands separators, so they are refused.
        if "." in text or _GROUPED.match(text):
            raise CellError("ambiguous number; use a dot for decimals and no separators")
        text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation as e:
        raise CellError("not a number") from e


def _iso_timestamp(moment: datetime) -> str:
    """The broker's form (JavaScript `toISOString`): UTC, milliseconds, `Z`."""
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def _date(value: Any) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return (_EPOCH + timedelta(days=int(value))).date().isoformat()
    text = str(value).strip()
    if m := _DMY.match(text):
        try:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        except ValueError as e:
            raise CellError("not a date") from e
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError as e:
        raise CellError("not a date") from e


def _timestamp(value: Any, tz: str) -> str:
    try:
        zone: Any = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        zone = UTC
    if isinstance(value, int | float) and not isinstance(value, bool):
        naive = _EPOCH + timedelta(days=float(value))
        return _iso_timestamp(naive.replace(tzinfo=zone))
    text = str(value).strip().replace(" ", "T", 1)
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as e:
        raise CellError("not a timestamp") from e
    # Text without a zone ("2025-02-01 11:08:44") is the sheet's local time,
    # as a date-time cell is.
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=zone)
    return _iso_timestamp(moment)


def from_cell(field: dict[str, Any], value: Any, *, tz: str = "UTC") -> Any:
    """The field value of a cell; None for an empty one. Raises CellError."""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return None
    kind = field["type"]
    if kind == "string":
        text = value if isinstance(value, str) else _plain(value)
        if len(text) > field.get("maxLength", 10**9):
            raise CellError(f"at most {field['maxLength']} characters")
        return text
    if kind == "integer":
        number = _number(value)
        if number != number.to_integral_value():
            raise CellError("not an integer")
        return int(number)
    if kind == "decimal":
        number = _number(value)
        scale = int(field.get("scale", 2))
        return f"{number.quantize(Decimal(1).scaleb(-scale)):f}"
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise CellError("not a yes/no value")
    if kind == "date":
        return _date(value)
    if kind == "timestamptz":
        return _timestamp(value, tz)
    if kind == "uuid":
        try:
            return str(UUID(str(value).strip()))
        except ValueError as e:
            raise CellError("not a UUID") from e
    if kind == "enum":
        text = str(value).strip()
        if text not in field.get("values", []):
            raise CellError("value is not one of the allowed values")
        return text
    raise CellError("unsupported field type")


def _plain(value: Any) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def from_app(field: dict[str, Any], value: Any) -> Any:
    """The broker's value in the same form `from_cell` returns."""
    if value is None or (field["type"] == "string" and value == ""):
        return None
    if field["type"] == "integer":
        # Beyond 2^53 the broker sends integers as text.
        return int(value)
    if field["type"] == "decimal":
        scale = int(field.get("scale", 2))
        return f"{Decimal(str(value)).quantize(Decimal(1).scaleb(-scale)):f}"
    if field["type"] == "timestamptz":
        return _iso_timestamp(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    return value


def to_cell(field: dict[str, Any], value: Any) -> dict[str, Any]:
    """`CellData` for `updateCells` with fields `userEnteredValue,userEnteredFormat.numberFormat`."""
    if value is None:
        return {}
    kind = field["type"]
    if kind == "boolean":
        return {"userEnteredValue": {"boolValue": bool(value)}}
    if kind == "integer":
        return {"userEnteredValue": {"numberValue": value}}
    if kind == "decimal":
        number = Decimal(value)
        # A number when a double holds it exactly, text otherwise.
        if Decimal(repr(float(number))) == number:
            return {"userEnteredValue": {"numberValue": float(number)}}
        return {"userEnteredValue": {"stringValue": value}}
    if kind == "date":
        days = (date.fromisoformat(value) - _EPOCH.date()).days
        return {
            "userEnteredValue": {"numberValue": days},
            "userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"}},
        }
    return {"userEnteredValue": {"stringValue": str(value)}}
