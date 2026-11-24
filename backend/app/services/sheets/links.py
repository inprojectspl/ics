"""The link of a micro-application to a Google Sheets file and the mappings
of its collections to the file's tabs (ADR-0031, ADR-0033).

Configured by an owner-like role; `owner_account` only by the asset's own
owner, since it lends that person's Google account to everyone who may run
the sync. Every change bumps `revision`, so a preview made under the old
mappings or account cannot be applied. A save states the whole link: the
mappings given are the mappings linked, matched to the stored ones by
collection, so a mapping kept keeps its agreed values.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import Text, and_, cast, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app import audit
from app.domain_errors import AccessDeniedError, ConflictError, InvalidInputError, NotFoundError
from app.models import (
    Asset,
    MicroAppEnvironment,
    MicroAppRelease,
    SheetBase,
    SheetLink,
    SheetMapping,
    SheetOperation,
    User,
)
from app.services.micro_applications import access
from app.services.micro_applications.common import load_app

from .book import Book
from .mapping_rules import (
    MAX_MAPPINGS,
    collection_def,
    linked,
    mapping_spec,
    owners,
    read_only,
    same_tab,
)

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


def field_defs(manifest: dict[str, Any], mapping: SheetMapping) -> dict[str, dict[str, Any]]:
    """The definitions of the mapping's linked fields, its tab field among them."""
    fields = collection_def(manifest, mapping.collection).get("fields") or {}
    return {f: fields[f] for f in owners(mapping) if f in fields}


async def mappings_of(session: AsyncSession, link: SheetLink) -> list[SheetMapping]:
    rows = await session.scalars(
        select(SheetMapping)
        .where(SheetMapping.link_id == link.id)
        .order_by(SheetMapping.position, SheetMapping.collection)
    )
    return list(rows)


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


# An operation that may still write to the file: its app part committing, or
# its sheet write not known to have landed. While one exists no other sync of
# the file may plan rows, or both would append the same record.
UNSETTLED = ("pending", "uncertain")
_BUSY = or_(
    SheetOperation.state == "applying",
    and_(SheetOperation.state == "applied", SheetOperation.google_status.in_(UNSETTLED)),
)


def busy_clause(link_id: UUID, *, but: UUID | None = None) -> Any:
    clause = and_(SheetOperation.link_id == link_id, _BUSY)
    return and_(clause, SheetOperation.id != but) if but is not None else clause


async def busy_operation(session: AsyncSession, link: SheetLink) -> SheetOperation | None:
    """The operation still settling, if any; without its preview and export,
    which can be large and are not needed to decide."""
    op: SheetOperation | None = await session.scalar(
        select(SheetOperation)
        .options(defer(SheetOperation.preview), defer(SheetOperation.export))
        .where(busy_clause(link.id))
        .limit(1)
    )
    return op


async def refuse_while_busy(session: AsyncSession, link: SheetLink) -> None:
    """A sync whose app part may have committed, or whose sheet write is not
    settled, finishes under the mappings it was planned with, and before any
    other sync plans rows of the same file."""
    busy = await busy_operation(session, link)
    if busy is None:
        return
    if busy.state == "applying":
        raise ConflictError("sheet_sync_in_progress", "a sync of this sheet is being applied")
    raise ConflictError(
        "sheet_sync_unsettled",
        "the sheet write of an earlier sync is not confirmed; check it first",
        extra={"operation_id": str(busy.id)},
    )


# ------------------------------------------------------------------ saving


async def _reset_base(session: AsyncSession, mapping: SheetMapping, before: dict[str, Any]) -> None:
    """Agreed values the new mapping no longer vouches for: the fields whose
    column header or owner changed, or that left the mapping. Kept, they
    would read a value of another column as the last agreed one and import it
    without a conflict. Tabs joining or leaving keep the other tabs' values:
    a record whose tab left is reported, never appended again."""
    new = linked(mapping.columns, mapping.tab_field)
    old = linked(before["columns"], before["tab_field"])
    changed = [f for f, was in old.items() if new.get(f) != was]
    if changed:
        await session.execute(
            update(SheetBase)
            .where(SheetBase.mapping_id == mapping.id)
            .values(values=SheetBase.values.op("-")(cast(changed, ARRAY(Text))))
        )


async def save(
    session: AsyncSession, user: User, asset_id: UUID, body: dict[str, Any]
) -> tuple[SheetLink, list[SheetMapping]]:
    asset, env = await _require_manage(session, user, asset_id)
    mode = body["account_mode"]
    if mode == "owner_account" and asset.owner_id != user.id:
        raise AccessDeniedError(
            "owner_account_owner_only", "only the asset's owner lends their own Google account"
        )
    manifest = await manifest_of(session, env)
    specs = body["mappings"]
    if not specs or len(specs) > MAX_MAPPINGS:
        raise InvalidInputError(
            "mappings_invalid", f"link 1..{MAX_MAPPINGS} collections", field="mappings"
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
    stored: dict[str, SheetMapping] = {}
    whole = bool(body.get("reset_base"))
    if link is not None:
        expected = body.get("expected_revision")
        if expected is not None and expected != link.revision:
            raise ConflictError("sheet_link_changed", "the link changed meanwhile; reload it")
        await refuse_while_busy(session, link)
        stored = {m.collection: m for m in await mappings_of(session, link)}
        whole = whole or link.spreadsheet_id != spreadsheet_id

    # Everything is checked before anything changes.
    wanted: list[dict[str, Any]] = []
    for i, spec in enumerate(specs):
        if any(w["collection"] == spec["collection"] for w in wanted):
            raise InvalidInputError(
                "mapping_duplicate", "each collection once", field=f"mappings/{i}/collection"
            )
        old = None if whole else stored.get(spec["collection"])
        wanted.append(mapping_spec(manifest, spec, old, f"mappings/{i}"))
    seen: list[dict[str, Any]] = []
    for i, w in enumerate(wanted):
        for tab in w["tabs"]:
            if any(same_tab(tab, t) for t in seen):
                raise InvalidInputError(
                    "sheet_tab_ambiguous",
                    "a tab belongs to one collection only",
                    field=f"mappings/{i}/tabs",
                )
            seen.append(tab)
    auto = bool(body.get("auto_sync", False))
    if auto and mode != "owner_account":
        raise InvalidInputError(
            "auto_sync_needs_owner_account",
            "an automatic sync runs on the owner's Google account",
            field="auto_sync",
        )

    if link is None:
        link = SheetLink(asset_id=asset_id, created_by=user.id, revision=1)
        session.add(link)
    else:
        link.revision += 1
    link.spreadsheet_id = spreadsheet_id
    link.account_mode = mode
    link.paused = bool(body.get("paused", False))
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

    keep = {w["collection"] for w in wanted} if not whole else set()
    for name, m in stored.items():
        if name not in keep:
            # Its agreed values go with it (cascade).
            await session.delete(m)
    await session.flush()
    mappings = []
    for position, w in enumerate(wanted):
        kept = stored.get(w["collection"]) if w["collection"] in keep else None
        if kept is None:
            m = SheetMapping(link_id=link.id, **w, position=position)
            session.add(m)
        else:
            m = kept
            before = {"columns": m.columns, "tab_field": m.tab_field}
            for k, v in w.items():
                setattr(m, k, v)
            m.position = position
            await session.flush()
            await _reset_base(session, m, before)
        mappings.append(m)
    await session.flush()
    await audit.record(
        session,
        actor=user,
        action="sheet_link_saved",
        target=str(asset_id),
        payload={
            "collections": [m.collection for m in mappings],
            "mode": mode,
            "revision": link.revision,
        },
    )
    return link, mappings


async def pin_tabs(session: AsyncSession, mappings: list[SheetMapping], book: Book) -> None:
    """Remember the tab ids a read resolved by name and the tabs' current
    names; the identity of a tab is its id from then on."""
    for m in mappings:
        now = [t.ref() for t in book[str(m.id)].tabs]
        if now != m.tabs:
            await session.execute(
                update(SheetMapping).where(SheetMapping.id == m.id).values(tabs=now)
            )
            m.tabs = now


async def remove(session: AsyncSession, user: User, asset_id: UUID) -> None:
    await _require_manage(session, user, asset_id)
    link = await require(session, asset_id, lock=True)
    await session.delete(link)
    await audit.record(session, actor=user, action="sheet_link_removed", target=str(asset_id))


def mapping_view(m: SheetMapping) -> dict[str, Any]:
    return {
        "id": str(m.id),
        "collection": m.collection,
        "tabs": m.tabs,
        "key_field": m.key_field,
        "tab_field": m.tab_field,
        "columns": m.columns,
        # Only the sheet's columns: the app reads the tabs, never writes them.
        "read_only": read_only(m.columns),
    }


def view(link: SheetLink, mappings: list[SheetMapping]) -> dict[str, Any]:
    return {
        "spreadsheet_id": link.spreadsheet_id,
        "spreadsheet_url": f"https://docs.google.com/spreadsheets/d/{link.spreadsheet_id}/edit",
        "mappings": [mapping_view(m) for m in mappings],
        "account_mode": link.account_mode,
        "revision": link.revision,
        "paused": link.paused,
        "auto_sync": link.auto_sync,
        "auto_checked_at": link.auto_checked_at.isoformat() if link.auto_checked_at else None,
        "auto_error": link.auto_error,
    }
