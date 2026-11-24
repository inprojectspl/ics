"""What every sync step shares: rights, the broker, Google tokens, reading
the file and the base (ADR-0031, ADR-0033)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain_errors import (
    AccessDeniedError,
    ConflictError,
    DomainError,
    InvalidInputError,
    NotFoundError,
    UnavailableError,
)
from app.models import (
    Asset,
    MicroAppEnvironment,
    SheetBase,
    SheetLink,
    SheetMapping,
    SheetOperation,
    User,
)
from app.services.micro_applications.common import broker_admin

from . import google, grants, links, mapping_rules
from .book import Book, Sheet, locate, read_book, tab_at

_BASE_CHUNK = 2000


class BrokerUnavailableError(UnavailableError):
    """The broker or Google did not answer; the same request can be repeated."""


# ------------------------------------------------------------------ helpers


def google_error(e: google.GoogleError) -> DomainError:
    extra: dict[str, Any] = {}
    if e.code in ("google_not_connected", "google_grant_invalid"):
        extra["action"] = "connect_google"
    elif e.code in ("google_no_access", "google_not_found"):
        extra["action"] = "request_access"
    if e.retryable:
        return BrokerUnavailableError(e.code, e.detail, extra=extra or None)
    return ConflictError(e.code, e.detail, extra=extra or None)


# Broker answers after which the transaction may have committed: only these
# leave an operation to resume with the same key. Any other answer comes
# after a rollback, so the operation failed and nothing was applied.
_UNKNOWN_OUTCOME = frozenset({"commit_unknown", "broker_error"})


async def call_broker(
    settings: Settings, path: str, body: dict[str, Any], *, timeout: float = 40.0
) -> dict[str, Any]:
    try:
        return await broker_admin(settings, "POST", path, body, timeout=timeout)
    except httpx.HTTPStatusError as e:
        try:
            err = e.response.json()
        except ValueError:
            err = {}
        # No code: a proxy's 502/504, not the broker's own answer.
        code = str(err.get("code") or "broker_error")
        extra = {k: err[k] for k in ("pointer", "change", "current_revision") if k in err}
        if code in _UNKNOWN_OUTCOME:
            raise BrokerUnavailableError(
                "broker_unavailable", "the application runtime did not finish", extra=extra
            ) from e
        if code in ("forbidden", "field_not_readable", "operation_not_available"):
            raise AccessDeniedError(code, str(err.get("detail", code)), extra=extra) from e
        if code == "invalid_state":
            raise ConflictError(
                "app_rule_refused", "the app's rules do not let this record change now", extra=extra
            ) from e
        if code in ("revision_mismatch", "not_found", "release_changed"):
            raise ConflictError(
                "app_changed", "the app changed since the preview", extra=extra
            ) from e
        if code == "validation_failed":
            raise InvalidInputError(code, str(err.get("detail", code)), extra=extra) from e
        raise ConflictError(code, str(err.get("detail", code)), extra=extra) from e
    except httpx.HTTPError as e:
        raise BrokerUnavailableError(
            "broker_unavailable", "the application runtime is unreachable"
        ) from e


def grant_user_of(op: SheetOperation) -> UUID:
    if op.google_user_id is None:
        raise ConflictError("google_not_connected", "the account of this sync is gone")
    return op.google_user_id


def google_user_for(link: SheetLink, asset: Asset, actor: User) -> UUID:
    return asset.owner_id if link.account_mode == "owner_account" else actor.id


async def token_for(session: AsyncSession, settings: Settings, user_id: UUID) -> str:
    try:
        return await grants.access_token(session, settings, user_id)
    except google.GoogleError as e:
        raise google_error(e) from e


async def row_limit(session: AsyncSession, settings: Settings, asset: Asset) -> int:
    """Rows a link of this app may sync: its owner's limit under the
    deployment's ceiling."""
    own = await session.scalar(select(User.sheet_max_rows).where(User.id == asset.owner_id))
    return min(own or 0, settings.google_sheets_max_rows)


async def fetch_book(
    token: str, link: SheetLink, mappings: list[SheetMapping], max_rows: int
) -> Book:
    try:
        return await read_book(token, link.spreadsheet_id, mappings, max_rows)
    except google.GoogleError as e:
        raise google_error(e) from e


async def runnable_link(
    session: AsyncSession, user: User, asset_id: UUID
) -> tuple[Asset, SheetLink, MicroAppEnvironment, list[SheetMapping]]:
    asset, env, rights = await links.rights_for(session, user, asset_id)
    if not rights.control:
        raise AccessDeniedError("forbidden", "running the sync needs the app.control right")
    link = await links.require(session, asset_id)
    if link.paused:
        raise ConflictError("sheet_link_paused", "the sheet link is paused")
    return asset, link, env, await links.mappings_of(session, link)


async def operation(
    session: AsyncSession, link: SheetLink, op_id: UUID, *, lock: bool = False
) -> SheetOperation:
    stmt = select(SheetOperation).where(
        SheetOperation.id == op_id, SheetOperation.link_id == link.id
    )
    if lock:
        stmt = stmt.with_for_update()
    op = await session.scalar(stmt)
    if op is None:
        raise NotFoundError("sheet_operation_not_found", "no such operation")
    return op


def update_conditions(manifest: dict[str, Any], mapping: SheetMapping) -> dict[str, Any]:
    """Conditions of the app's update rule that the linked fields let us check."""
    conditions = (
        mapping_rules.update_rule(mapping_rules.collection_def(manifest, mapping.collection)).get(
            "conditions"
        )
        or {}
    )
    linked = mapping_rules.owners(mapping)
    return {f: v for f, v in conditions.items() if f in linked}


def required_fields(manifest: dict[str, Any], mapping: SheetMapping) -> list[str]:
    fields = mapping_rules.collection_def(manifest, mapping.collection).get("fields") or {}
    return [name for name, f in fields.items() if f.get("required") and "default" not in f]


def placer(part: dict[str, Any]) -> Callable[[int], list[int]]:
    """A function giving [sheet_id, row in that tab] of a row a preview part
    counts across its tabs; the tabs are indexed once."""
    tabs = part["sheet"]["tabs"]
    firsts = [t["first"] for t in tabs]

    def place(row: int) -> list[int]:
        i, own = tab_at(firsts, row)
        return [tabs[i]["sheet_id"], own]

    return place


async def save_base(
    session: AsyncSession,
    mapping_id: str,
    agreed: Mapping[str, Mapping[str, Any]],
    rows: Mapping[str, list[int]] | None = None,
) -> None:
    """Merge agreed values and the tab rows records were seen in into the
    base, one statement per chunk."""
    rows = rows or {}
    mid = UUID(mapping_id)
    entries = [
        {
            "mapping_id": mid,
            "record_id": UUID(rid),
            "values": dict(agreed.get(rid) or {}),
            "sheet_id": rows[rid][0] if rid in rows else None,
            "row": rows[rid][1] if rid in rows else None,
        }
        for rid in {*agreed, *rows}
        if agreed.get(rid) or rid in rows
    ]
    for start in range(0, len(entries), _BASE_CHUNK):
        stmt = insert(SheetBase).values(entries[start : start + _BASE_CHUNK])
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[SheetBase.mapping_id, SheetBase.record_id],
                set_={
                    "values": SheetBase.values.op("||")(stmt.excluded["values"]),
                    "sheet_id": func.coalesce(stmt.excluded["sheet_id"], SheetBase.sheet_id),
                    "row": func.coalesce(stmt.excluded["row"], SheetBase.row),
                },
            )
        )


def placed(part: dict[str, Any], sheet: Sheet) -> dict[int, int] | None:
    """Where the rows a preview part touched are now, or None when a tab's
    linked columns or one of those rows changed since."""
    then = {t["sheet_id"]: t["cols"] for t in part["sheet"]["tabs"]}
    for tab in sheet.tabs:
        if tab.sheet_id in then and then[tab.sheet_id] != tab.cols:
            return None
    if part["sheet"]["cols"] != sheet.cols:
        return None
    return locate(part["snapshot"], sheet, sheet.cols)
