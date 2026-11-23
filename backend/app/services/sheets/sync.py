"""Preview, apply and check one sync of a sheet link (ADR-0031).

A person runs these, and so does the automatic sync (`auto`, ADR-0032)
as the asset owner. `preview` reads the sheet and the app's records and
stores what would change; `apply` takes the person's decisions,
checks that neither side moved, commits the app's part through the broker
(once per operation, whatever the retries) and then writes the sheet in one
atomic `batchUpdate`, after reading it again. A write whose answer is lost
stays `uncertain` until `check` reads the cells back; it is never sent twice.

The comparison is three-way per cell: the app's value, the sheet's value and
the base, the value both sides agreed on at the last sync. A column owned by
one side flows one way only; a column owned by both takes whichever side
changed, and a cell both changed is a conflict a person decides.

No database transaction stays open across a call to Google or the broker;
every state change is conditional on the state it leaves, so two requests
resuming the same operation cannot both finish it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.config import Settings
from app.domain_errors import (
    ConflictError,
    DomainError,
    InvalidInputError,
    LimitExceededError,
    NotFoundError,
)
from app.models import Asset, MicroAppEnvironment, SheetBase, SheetLink, SheetOperation, User

from . import links, values, write
from .common import (
    BrokerUnavailableError,
    call_broker,
    fetch_sheet,
    google_user_for,
    grant_user_of,
    operation,
    placed,
    required_fields,
    row_limit,
    runnable_link,
    save_base,
    token_for,
    update_conditions,
)
from .compare import UNCONFIRMED, Sheet, compare

# ------------------------------------------------------------------ helpers


async def _move(session: AsyncSession, op_id: UUID, source: str, **changes: Any) -> bool:
    """Change an operation only if its state is still `source`; commits."""
    moved = await session.scalar(
        update(SheetOperation)
        .where(SheetOperation.id == op_id, SheetOperation.state == source)
        .values(**changes)
        .returning(SheetOperation.id)
    )
    await session.commit()
    return moved is not None


# ------------------------------------------------------------------ preview


async def linked_sheet(
    session: AsyncSession, settings: Settings, user: User, asset_id: UUID
) -> Sheet:
    """The linked columns of the sheet as they are now, read as `user`."""
    asset, link, _ = await runnable_link(session, user, asset_id)
    limit = await row_limit(session, settings, asset)
    token = await token_for(session, settings, google_user_for(link, asset, user))
    await session.commit()  # no transaction across the call below
    return await fetch_sheet(token, link, limit)


async def _plan(
    session: AsyncSession,
    settings: Settings,
    user: User,
    asset_id: UUID,
    sheet: Sheet | None = None,
) -> tuple[SheetLink, UUID, dict[str, Any]]:
    """Read both sides (the sheet unless given) and compare them; stores nothing."""
    asset, link, env = await runnable_link(session, user, asset_id)
    await links.refuse_while_applying(session, link)
    manifest = await links.manifest_of(session, env)
    fields = links.field_defs(manifest, link)
    if len(fields) != len(link.columns):
        raise ConflictError("sheet_link_outdated", "a linked field is gone from the active release")
    google_user = google_user_for(link, asset, user)
    base: dict[str, dict[str, Any]] = {}
    seen_at: dict[str, int | None] = {}
    for b in await session.scalars(select(SheetBase).where(SheetBase.link_id == link.id)):
        base[str(b.record_id)] = b.values
        seen_at[str(b.record_id)] = b.row
    limit = await row_limit(session, settings, asset)
    token = await token_for(session, settings, google_user)
    await session.commit()  # no transaction across the calls below
    read_app = call_broker(
        settings,
        f"/admin/apps/{env.asset_hex}/prod/sheets/read",
        {
            "user_id": str(user.id),
            "collection": link.collection,
            "fields": list(fields),
            "limit": limit,
        },
    )
    if sheet is None:
        sheet, read = await asyncio.gather(fetch_sheet(token, link, limit), read_app)
    else:
        read = await read_app
    if read.get("truncated"):
        raise LimitExceededError(
            "collection_too_large",
            f"the app owner's limit is {limit} rows",
            extra={"limit": limit},
        )
    plan = compare(
        link,
        fields,
        sheet,
        read["rows"],
        base,
        seen_at,
        required_fields(manifest, link),
        update_conditions(manifest, link),
    )
    plan["release"] = read.get("release")
    return link, google_user, plan


async def _store(
    session: AsyncSession,
    user: User,
    link: SheetLink,
    google_user: UUID,
    plan: dict[str, Any],
    *,
    auto: bool,
) -> SheetOperation:
    # Earlier previews can no longer be applied; their details go.
    await session.execute(
        update(SheetOperation)
        .where(SheetOperation.link_id == link.id, SheetOperation.state == "previewed")
        .values(state="superseded", preview={})
    )
    op = SheetOperation(
        link_id=link.id,
        link_revision=link.revision,
        actor_id=user.id,
        google_user_id=google_user,
        state="previewed",
        google_status="none",
        summary=plan["summary"],
        preview=plan,
        auto=auto,
    )
    session.add(op)
    await session.commit()
    return op


async def preview(
    session: AsyncSession, settings: Settings, user: User, asset_id: UUID
) -> tuple[SheetOperation, SheetLink]:
    link, google_user, plan = await _plan(session, settings, user, asset_id)
    return await _store(session, user, link, google_user, plan, auto=False), link


# What makes an automatic preview worth a row: something to apply, or
# conflicts a person decides. Issues alone are shown by a person's preview.
_WORTH_STORING = ("imports", "exports", "creates", "appends", "conflicts")


async def auto_preview(
    session: AsyncSession,
    settings: Settings,
    owner: User,
    asset_id: UUID,
    sheet: Sheet | None = None,
) -> SheetOperation | None:
    """An automatic run's preview, stored only when it is worth a row: most
    runs find nothing to do and leave nothing behind."""
    link, google_user, plan = await _plan(session, settings, owner, asset_id, sheet)
    if not any(plan["summary"].get(k) for k in _WORTH_STORING):
        return None
    return await _store(session, owner, link, google_user, plan, auto=True)


# -------------------------------------------------------------------- apply


def _decide(op: SheetOperation, decisions: Mapping[str, str]) -> dict[str, Any]:
    """The app changes the decisions give and the values both sides will
    agree on: `local_base` once the app commits, `remote_base` once the
    sheet write is confirmed; `rows` where each record was seen."""
    plan = op.preview
    patches: list[dict[str, Any]] = []
    local_base: dict[str, dict[str, Any]] = {}
    remote_base: dict[str, dict[str, Any]] = {}
    undecided = []
    for u in plan["updates"]:
        rid = u["record_id"]
        patch = dict(u["import"])
        export = dict(u["export"])
        for c in u["conflicts"]:
            choice = decisions.get(f"{rid}:{c['field']}")
            if choice == "sheet":
                patch[c["field"]] = c["sheet"]
            elif choice == "app":
                export[c["field"]] = c["app"]
            else:
                undecided.append(f"{rid}:{c['field']}")
        if patch:
            patches.append({"op": "update", "id": rid, "revision": u["revision"], "patch": patch})
        local_base[rid] = {**u["same"], **patch}
        remote_base[rid] = export
    if undecided:
        raise InvalidInputError(
            "decisions_missing", "decide every conflict", extra={"undecided": undecided}
        )
    rows = dict(plan["rows"])
    for c in plan["creates"]:
        patches.append({"op": "create", "id": c["record_id"], "data": c["data"]})
        local_base[c["record_id"]] = dict(c["data"])
        rows[c["record_id"]] = c["row"]
    for c in plan["converged"]:
        local_base.setdefault(c["record_id"], {}).update(c["values"])
    for a in plan["appends"]:
        # Until the write is confirmed a missing row means "append again".
        local_base[a["record_id"]] = {**a["values"], UNCONFIRMED: True}
        remote_base[a["record_id"]] = {UNCONFIRMED: False}
    return {
        "patches": patches,
        "local_base": local_base,
        "remote_base": remote_base,
        "rows": rows,
    }


async def _reserve(
    session: AsyncSession,
    settings: Settings,
    asset: Asset,
    link: SheetLink,
    op: SheetOperation,
    google_user: UUID,
    decisions: Mapping[str, str],
) -> None:
    """`previewed` -> `applying`, after checking that neither the link nor the
    rows the preview touched changed and that no other sync is applying."""
    if op.link_revision != link.revision or op.google_user_id != google_user:
        await _move(session, op.id, "previewed", state="stale")
        raise ConflictError(
            "sheet_link_changed", "the link changed since the preview; preview again"
        )
    plan = _decide(op, decisions)
    limit = await row_limit(session, settings, asset)
    token = await token_for(session, settings, grant_user_of(op))
    await session.commit()
    if placed(op.preview, link, await fetch_sheet(token, link, limit)) is None:
        await _move(session, op.id, "previewed", state="stale")
        raise ConflictError("sheet_changed", "the sheet changed since the preview; preview again")
    other = exists().where(
        SheetOperation.link_id == link.id,
        SheetOperation.state == "applying",
        SheetOperation.id != op.id,
    )
    same_link = exists().where(SheetLink.id == link.id, SheetLink.revision == op.link_revision)
    won = await session.scalar(
        update(SheetOperation)
        .where(SheetOperation.id == op.id, SheetOperation.state == "previewed", ~other, same_link)
        .values(state="applying", decisions=dict(decisions), export=plan)
        .returning(SheetOperation.id)
    )
    await session.commit()
    await session.refresh(op)
    if won is None and op.state not in ("applying", "applied"):
        raise ConflictError("sheet_sync_in_progress", "another sync of this sheet is being applied")


async def apply(
    session: AsyncSession,
    settings: Settings,
    user: User,
    asset_id: UUID,
    op_id: UUID,
    decisions: Mapping[str, str],
) -> tuple[SheetOperation, SheetLink]:
    asset, link, env = await runnable_link(session, user, asset_id)
    op = await operation(session, link, op_id)
    if op.actor_id != user.id:
        raise NotFoundError("sheet_operation_not_found", "no such preview of yours")
    if op.state == "previewed":
        await _reserve(
            session, settings, asset, link, op, google_user_for(link, asset, user), decisions
        )
    if op.state == "applied":
        return op, link  # A repeated request: the outcome is already recorded.
    if op.state != "applying":
        raise ConflictError(f"sheet_operation_{op.state}", "this preview can no longer be applied")

    plan = op.export or {}
    done: dict[str, Any] = {"results": []}
    if plan["patches"]:
        try:
            done = await call_broker(
                settings,
                f"/admin/apps/{env.asset_hex}/prod/sheets/apply",
                {
                    "user_id": str(user.id),
                    "collection": link.collection,
                    "key": str(op.id),
                    "changes": plan["patches"],
                    "fields": [c["field"] for c in link.columns],
                    "release": op.preview.get("release"),
                },
                # The broker's deadline for one transaction grows with its
                # changes (sheets.js applyDeadlineMs); wait a little longer.
                timeout=min(330.0, 40.0 + 0.02 * len(plan["patches"])),
            )
        except BrokerUnavailableError:
            raise  # Stays `applying`: the same request resumes with the same key.
        except DomainError as e:
            # The broker rolled back: nothing was applied.
            state = "stale" if e.code == "app_changed" else "failed"
            await _move(session, op.id, "applying", state=state, error=e.code[:64])
            raise

    op = await operation(session, link, op.id, lock=True)
    if op.state != "applying":
        await session.commit()
        return op, link  # Another request finished it meanwhile.
    created = await _created_values(session, env, link, done["results"])
    await save_base(session, link.id, plan["local_base"], plan["rows"])
    # The automatic sync's idle shortcut no longer holds after an apply.
    await session.execute(
        update(SheetLink).where(SheetLink.id == link.id).values(auto_sheet_hash=None)
    )
    # A created record's own columns reach its row with the write.
    remote = dict(plan["remote_base"])
    for c in op.preview["creates"]:
        remote[c["record_id"]] = created.get(c["record_id"], {})
    op.export = {**plan, "created": created, "remote_base": remote}
    op.state = "applied"
    op.google_status = "pending"
    op.result = {"app_changes": len(done["results"]), "replayed": bool(done.get("replayed"))}
    await audit.record(
        session,
        actor=user,
        action="sheet_sync_applied",
        target=str(asset_id),
        payload={"operation": str(op.id), "app_changes": len(done["results"])},
    )
    await session.commit()
    await write.write(session, settings, asset, link, env, op)
    return op, link


async def _created_values(
    session: AsyncSession,
    env: MicroAppEnvironment,
    link: SheetLink,
    results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """The app's own columns of each created record (its defaults), for its row."""
    returned = [r for r in results if "values" in r]
    if not returned:
        return {}
    fields = links.field_defs(await links.manifest_of(session, env), link)
    app_owned = [c["field"] for c in link.columns if c["owner"] == "app" and c["field"] in fields]
    return {
        r["id"]: {f: values.from_app(fields[f], r["values"].get(f)) for f in app_owned}
        for r in returned
    }
