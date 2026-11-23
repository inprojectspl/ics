"""The link of a micro-application collection to a Google Sheets tab.

Configured by an owner-like role; `owner_account` only by the asset's own
owner, since it lends that person's Google account to everyone who may run
the sync. Every change bumps `revision`, so a preview made under the old
mapping or account cannot be applied.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import Text, cast, delete, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.domain_errors import AccessDeniedError, ConflictError, InvalidInputError, NotFoundError
from app.models import (
    Asset,
    MicroAppEnvironment,
    MicroAppRelease,
    SheetBase,
    SheetLink,
    SheetOperation,
    User,
)
from app.services.micro_applications import access
from app.services.micro_applications.common import load_app

from . import values
from .compare import norm_header

# The id in a spreadsheet URL: /spreadsheets/d/<id>/...
_URL_ID = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,128})")
_ID = re.compile(r"^[A-Za-z0-9_-]{20,128}$")


def spreadsheet_id_of(value: str) -> str:
    value = value.strip()
    if m := _URL_ID.search(value):
        return m[1]
    if _ID.match(value):
        return value
    raise InvalidInputError(
        "spreadsheet_invalid", "not a Google Sheets address or id", field="spreadsheet"
    )


async def manifest_of(session: AsyncSession, env: MicroAppEnvironment) -> dict[str, Any]:
    if env.active_release_id is None:
        raise ConflictError("app_not_ready", "the application has no active release")
    release = await session.get(MicroAppRelease, env.active_release_id)
    assert release is not None
    manifest: dict[str, Any] = release.manifest
    return manifest


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


def field_defs(manifest: dict[str, Any], link: SheetLink) -> dict[str, dict[str, Any]]:
    fields = collection_def(manifest, link.collection).get("fields") or {}
    return {c["field"]: fields[c["field"]] for c in link.columns if c["field"] in fields}


def _check_columns(
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


async def get(session: AsyncSession, asset_id: UUID, *, lock: bool = False) -> SheetLink | None:
    stmt = select(SheetLink).where(SheetLink.asset_id == asset_id)
    if lock:
        stmt = stmt.with_for_update()
    link: SheetLink | None = await session.scalar(stmt)
    return link


async def require(session: AsyncSession, asset_id: UUID, *, lock: bool = False) -> SheetLink:
    link = await get(session, asset_id, lock=lock)
    if link is None:
        raise NotFoundError("sheet_link_not_found", "the application is not linked to a sheet")
    return link


async def rights_for(
    session: AsyncSession, user: User, asset_id: UUID
) -> tuple[Asset, MicroAppEnvironment, access.Rights]:
    asset, env = await load_app(session, asset_id)
    rights = await access.rights(session, user, asset)
    if not rights.use:
        raise NotFoundError("not_found", "micro-application not found")
    return asset, env, rights


async def _require_manage(
    session: AsyncSession, user: User, asset_id: UUID
) -> tuple[Asset, MicroAppEnvironment]:
    asset, env, rights = await rights_for(session, user, asset_id)
    if not rights.manage:
        raise AccessDeniedError("forbidden", "only the application's owner configures its sheet")
    return asset, env


async def refuse_while_applying(session: AsyncSession, link: SheetLink) -> None:
    """A sync whose app part may have committed must finish under the mapping
    it was planned with."""
    busy = await session.scalar(
        select(SheetOperation.id).where(
            SheetOperation.link_id == link.id, SheetOperation.state == "applying"
        )
    )
    if busy is not None:
        raise ConflictError("sheet_sync_in_progress", "a sync of this sheet is being applied")


# A change of any of these makes every agreed value meaningless.
_WHOLE_BASE = ("collection", "spreadsheet_id", "sheet_title")


async def _reset_base(
    session: AsyncSession, link: SheetLink, before: dict[str, Any] | None, *, everything: bool
) -> None:
    """Agreed values the new mapping no longer vouches for: all of them for a
    new link or another sheet, tab or collection; the fields whose
    column header or owner changed otherwise. Kept, they would read a value of
    another column as the last agreed one and import it without a conflict."""
    if everything or before is None or any(before[k] != getattr(link, k) for k in _WHOLE_BASE):
        await session.execute(delete(SheetBase).where(SheetBase.link_id == link.id))
        return
    old = {c["field"]: c for c in before["columns"]}
    changed = [
        c["field"]
        for c in link.columns
        if c["field"] in old
        and (
            norm_header(old[c["field"]]["header"]) != norm_header(c["header"])
            or old[c["field"]]["owner"] != c["owner"]
        )
    ]
    changed += [f for f in old if f not in {c["field"] for c in link.columns}]
    if changed:
        await session.execute(
            update(SheetBase)
            .where(SheetBase.link_id == link.id)
            .values(values=SheetBase.values.op("-")(cast(changed, ARRAY(Text))))
        )


async def save(
    session: AsyncSession, user: User, asset_id: UUID, body: dict[str, Any]
) -> SheetLink:
    asset, env = await _require_manage(session, user, asset_id)
    mode = body["account_mode"]
    if mode == "owner_account" and asset.owner_id != user.id:
        raise AccessDeniedError(
            "owner_account_owner_only", "only the asset's owner lends their own Google account"
        )
    collection = collection_def(await manifest_of(session, env), body["collection"])
    key_field = body.get("key_field") or None
    columns = [
        {"field": c["field"], "header": c["header"].strip(), "owner": c["owner"]}
        for c in body["columns"]
    ]
    _check_columns(collection, columns, key_field)
    sheet_title = body["sheet_title"].strip()
    if not sheet_title:
        raise InvalidInputError(
            "sheet_title_invalid", "a tab name of 1..100 characters", field="sheet_title"
        )
    spreadsheet_id = spreadsheet_id_of(body["spreadsheet"])
    taken = await session.scalar(
        select(SheetLink.asset_id).where(
            SheetLink.spreadsheet_id == spreadsheet_id, SheetLink.asset_id != asset_id
        )
    )
    if taken is not None:
        raise ConflictError(
            "spreadsheet_already_linked", "another application already writes to this spreadsheet"
        )

    link = await get(session, asset_id, lock=True)
    before = None
    if link is None:
        link = SheetLink(asset_id=asset_id, created_by=user.id, revision=1)
        session.add(link)
    else:
        expected = body.get("expected_revision")
        if expected is not None and expected != link.revision:
            raise ConflictError("sheet_link_changed", "the link changed meanwhile; reload it")
        await refuse_while_applying(session, link)
        before = {k: getattr(link, k) for k in (*_WHOLE_BASE, "columns")}
        link.revision += 1
    link.collection = body["collection"]
    link.spreadsheet_id = spreadsheet_id
    link.sheet_title = sheet_title
    link.key_field = key_field
    link.columns = columns
    link.account_mode = mode
    link.paused = bool(body.get("paused", False))
    auto = bool(body.get("auto_sync", False))
    if auto and mode != "owner_account":
        raise InvalidInputError(
            "auto_sync_needs_owner_account",
            "an automatic sync runs on the owner's Google account",
            field="auto_sync",
        )
    if auto != link.auto_sync:
        link.auto_checked_at, link.auto_next_at, link.auto_error = None, None, None
    link.auto_sync = auto
    # Whatever changed in the link, the next automatic run compares in full.
    link.auto_sheet_hash = None
    try:
        await session.flush()
    except IntegrityError as e:
        raise ConflictError(
            "spreadsheet_already_linked", "another application already writes to this spreadsheet"
        ) from e
    await _reset_base(session, link, before, everything=bool(body.get("reset_base")))
    await audit.record(
        session,
        actor=user,
        action="sheet_link_saved",
        target=str(asset_id),
        payload={"collection": link.collection, "mode": mode, "revision": link.revision},
    )
    return link


async def remove(session: AsyncSession, user: User, asset_id: UUID) -> None:
    await _require_manage(session, user, asset_id)
    link = await require(session, asset_id, lock=True)
    await session.delete(link)
    await audit.record(session, actor=user, action="sheet_link_removed", target=str(asset_id))


def view(link: SheetLink) -> dict[str, Any]:
    return {
        "collection": link.collection,
        "spreadsheet_id": link.spreadsheet_id,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{link.spreadsheet_id}/edit",
        "sheet_title": link.sheet_title,
        "key_field": link.key_field,
        "columns": link.columns,
        "account_mode": link.account_mode,
        "revision": link.revision,
        "paused": link.paused,
        "auto_sync": link.auto_sync,
        "auto_checked_at": link.auto_checked_at.isoformat() if link.auto_checked_at else None,
        "auto_error": link.auto_error,
    }
