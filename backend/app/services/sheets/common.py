"""What every sync step shares: rights, the broker, Google tokens (ADR-0031)."""

from __future__ import annotations

from collections.abc import Mapping
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
from app.models import Asset, MicroAppEnvironment, SheetBase, SheetLink, SheetOperation, User
from app.services.micro_applications.common import broker_admin

from . import google, grants, links
from .compare import Sheet, layout, locate, read_sheet

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


async def fetch_sheet(token: str, link: SheetLink, max_rows: int) -> Sheet:
    try:
        return await read_sheet(token, link, max_rows)
    except google.GoogleError as e:
        raise google_error(e) from e


async def runnable_link(
    session: AsyncSession, user: User, asset_id: UUID
) -> tuple[Asset, SheetLink, MicroAppEnvironment]:
    asset, env, rights = await links.rights_for(session, user, asset_id)
    if not rights.control:
        raise AccessDeniedError("forbidden", "running the sync needs the app.control right")
    link = await links.require(session, asset_id)
    if link.paused:
        raise ConflictError("sheet_link_paused", "the sheet link is paused")
    return asset, link, env


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


def update_conditions(manifest: dict[str, Any], link: SheetLink) -> dict[str, Any]:
    """Conditions of the app's update rule that the linked fields let us check."""
    conditions = (
        links.update_rule(links.collection_def(manifest, link.collection)).get("conditions") or {}
    )
    linked = {c["field"] for c in link.columns}
    return {f: v for f, v in conditions.items() if f in linked}


def required_fields(manifest: dict[str, Any], link: SheetLink) -> list[str]:
    fields = links.collection_def(manifest, link.collection).get("fields") or {}
    return [name for name, f in fields.items() if f.get("required") and "default" not in f]


async def save_base(
    session: AsyncSession,
    link_id: UUID,
    agreed: Mapping[str, Mapping[str, Any]],
    rows: Mapping[str, int] | None = None,
) -> None:
    """Merge agreed values and the rows records were seen in into the base,
    one statement per chunk."""
    rows = rows or {}
    entries = [
        {
            "link_id": link_id,
            "record_id": UUID(rid),
            "values": dict(agreed.get(rid) or {}),
            "row": rows.get(rid),
        }
        for rid in {*agreed, *rows}
        if agreed.get(rid) or rid in rows
    ]
    for start in range(0, len(entries), _BASE_CHUNK):
        stmt = insert(SheetBase).values(entries[start : start + _BASE_CHUNK])
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[SheetBase.link_id, SheetBase.record_id],
                set_={
                    "values": SheetBase.values.op("||")(stmt.excluded["values"]),
                    "row": func.coalesce(stmt.excluded["row"], SheetBase.row),
                },
            )
        )


def placed(preview: dict[str, Any], link: SheetLink, sheet: Sheet) -> dict[int, int] | None:
    """Where the rows the preview touched are now, or None when the columns
    or one of those rows changed since."""
    try:
        cols = layout(link, sheet)
    except ConflictError:
        return None
    if cols != preview["sheet"]["cols"]:
        return None
    return locate(preview["snapshot"], sheet, cols)
