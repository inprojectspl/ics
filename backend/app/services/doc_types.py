"""Doc type vocabulary (ADR-0015, section 2): an organisation-wide table edited by
admins at runtime. Types are archived, never deleted, so assets keep the type
they were given. Nothing here commits.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import json_schema
from app.domain_errors import ConflictError, InvalidInputError, NotFoundError
from app.i18n import Locale
from app.models import DocType
from app.util import now as utc_now


def check_properties_schema(schema: Any) -> dict[str, Any]:
    """A schema in the supported subset whose root describes an object."""
    try:
        json_schema.check_schema(schema)
    except json_schema.SchemaError as exc:
        raise InvalidInputError("doc_type_schema_invalid", str(exc)) from None
    if schema.get("type", "object") != "object":
        raise InvalidInputError("doc_type_schema_invalid", "schema.type: must be 'object'")
    return schema


async def list_doc_types(session: AsyncSession, *, include_archived: bool) -> list[DocType]:
    stmt = select(DocType).order_by(DocType.position, DocType.key)
    if not include_archived:
        stmt = stmt.where(DocType.archived_at.is_(None))
    return list((await session.scalars(stmt)).all())


async def check_filter_keys(session: AsyncSession, keys: list[str]) -> None:
    """Refuse a list or search filter naming a type that does not exist. An
    archived type still filters (assets keep it); the error lists the active
    keys, the ones worth suggesting."""
    known = set(await session.scalars(select(DocType.key).where(DocType.key.in_(keys))))
    unknown = sorted(set(keys) - known)
    if not unknown:
        return
    active = await list_doc_types(session, include_archived=False)
    raise InvalidInputError(
        "doc_type_filter_unknown",
        f"unknown document type: {', '.join(unknown)}",
        field="doc_type",
        extra={"allowed": [t.key for t in active]},
    )


async def create_doc_type(session: AsyncSession, fields: Mapping[str, Any]) -> DocType:
    if await session.get(DocType, fields["key"]) is not None:
        raise ConflictError("doc_type_exists", f"document type {fields['key']} already exists")
    values = dict(fields)
    values["properties_schema"] = check_properties_schema(values.get("properties_schema") or {})
    doc_type = DocType(**values)
    session.add(doc_type)
    await session.flush()
    return doc_type


async def update_doc_type(
    session: AsyncSession, key: str, changes: Mapping[str, Any]
) -> tuple[DocType, list[str]]:
    """Apply `changes` (`archived` toggles `archived_at`); return the type and
    the names of the fields that changed."""
    doc_type = await session.get(DocType, key)
    if doc_type is None:
        raise NotFoundError("doc_type_not_found", f"document type {key} does not exist")
    changed: list[str] = []
    for name, value in changes.items():
        if name == "archived":
            if value == (doc_type.archived_at is not None):
                continue
            doc_type.archived_at = utc_now() if value else None
        else:
            if name == "properties_schema":
                value = check_properties_schema(value or {})
            if getattr(doc_type, name) == value:
                continue
            setattr(doc_type, name, value)
        changed.append(name)
    return doc_type, changed


def doc_type_row(doc_type: DocType, locale: Locale) -> dict[str, Any]:
    """Labels are data, not catalogue keys; the Polish label falls back to
    the English one, as `t()` does."""
    label = (doc_type.label_pl if locale == "pl" else None) or doc_type.label_en
    return {
        "key": doc_type.key,
        "label": label,
        "label_pl": doc_type.label_pl,
        "label_en": doc_type.label_en,
        "agent_hint": doc_type.agent_hint,
        "default_review_days": doc_type.default_review_days,
        "properties_schema": doc_type.properties_schema,
        "position": doc_type.position,
        "archived": doc_type.archived_at is not None,
        "archived_at": doc_type.archived_at.isoformat() if doc_type.archived_at else None,
    }
