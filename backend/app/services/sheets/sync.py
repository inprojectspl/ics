"""Preview, apply and check one sync of a sheet link (ADR-0031, ADR-0033).

A person runs these, and so does the automatic sync (`auto`, ADR-0032)
as the asset owner. One sync covers the whole file: every mapping of the
link. `preview` reads the linked tabs and the app's linked collections and
stores what would change, one part per mapping; `apply` takes the person's
decisions, checks that neither side moved, commits the app's part of every
collection through the broker in one transaction (once per operation,
whatever the retries) and then writes every tab in one atomic
`batchUpdate`, after reading the file again. A write whose answer is lost
stays `uncertain` until `check` reads the cells back; it is never sent
twice, and no other sync of the file plans rows until it is settled.

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
from app.models import (
    Asset,
    MicroAppEnvironment,
    SheetBase,
    SheetLink,
    SheetMapping,
    SheetOperation,
    User,
)

from . import links, mapping_rules, values, write
from .book import Book
from .common import (
    BrokerUnavailableError,
    call_broker,
    fetch_book,
    google_user_for,
    grant_user_of,
    operation,
    placed,
    placer,
    required_fields,
    row_limit,
    runnable_link,
    save_base,
    token_for,
    update_conditions,
)
from .compare import UNCONFIRMED, compare

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


def _parts(op: SheetOperation) -> dict[str, dict[str, Any]]:
    parts: dict[str, dict[str, Any]] = op.preview.get("mappings") or {}
    return parts


def _total(parts: list[dict[str, Any]]) -> dict[str, int]:
    total: dict[str, int] = {}
    for part in parts:
        for k, v in part["summary"].items():
            total[k] = total.get(k, 0) + v
    return total


# ------------------------------------------------------------------ preview


async def linked_book(
    session: AsyncSession, settings: Settings, user: User, asset_id: UUID
) -> Book:
    """The linked columns of every linked tab as they are now, read as `user`."""
    asset, link, _, mappings = await runnable_link(session, user, asset_id)
    limit = await row_limit(session, settings, asset)
    token = await token_for(session, settings, google_user_for(link, asset, user))
    await session.commit()  # no transaction across the call below
    return await fetch_book(token, link, mappings, limit)


async def _plan(
    session: AsyncSession,
    settings: Settings,
    user: User,
    asset_id: UUID,
    book: Book | None = None,
) -> tuple[SheetLink, UUID, dict[str, Any]]:
    """Read both sides (the file unless given) and compare every mapping;
    stores nothing but the tab ids the read pinned."""
    asset, link, env, mappings = await runnable_link(session, user, asset_id)
    await links.refuse_while_busy(session, link)
    manifest = await links.manifest_of(session, env)
    fields = {}
    for m in mappings:
        fields[m.id] = links.field_defs(manifest, m)
        if len(fields[m.id]) != len(mapping_rules.owners(m)):
            raise ConflictError(
                "sheet_link_outdated",
                f"a field linked in {m.collection!r} is gone from the active release",
                extra={"collection": m.collection},
            )
    google_user = google_user_for(link, asset, user)
    base: dict[UUID, dict[str, dict[str, Any]]] = {m.id: {} for m in mappings}
    seen: dict[UUID, dict[str, tuple[int | None, int | None]]] = {m.id: {} for m in mappings}
    for b in await session.scalars(
        select(SheetBase).where(SheetBase.mapping_id.in_([m.id for m in mappings]))
    ):
        base[b.mapping_id][str(b.record_id)] = b.values
        seen[b.mapping_id][str(b.record_id)] = (b.sheet_id, b.row)
    limit = await row_limit(session, settings, asset)
    token = await token_for(session, settings, google_user)
    await session.commit()  # no transaction across the calls below
    read_app = call_broker(
        settings,
        f"/admin/apps/{env.asset_hex}/prod/sheets/read",
        {
            "user_id": str(user.id),
            "collections": [
                {"collection": m.collection, "fields": list(fields[m.id])} for m in mappings
            ],
            "limit": limit,
        },
    )
    if book is None:
        book, read = await asyncio.gather(fetch_book(token, link, mappings, limit), read_app)
    else:
        read = await read_app
    assert book is not None
    if read.get("truncated"):
        raise LimitExceededError(
            "collection_too_large",
            f"the app owner's limit is {limit} rows",
            extra={"limit": limit},
        )
    await links.pin_tabs(session, mappings, book)
    await session.commit()
    parts: dict[str, dict[str, Any]] = {}
    for m in mappings:
        sheet = book[str(m.id)]
        seen_at: dict[str, int | None] = {}
        for rid, (sheet_id, row) in seen[m.id].items():
            tab = sheet.tab(sheet_id)
            seen_at[rid] = tab.first + row if tab is not None and row is not None else None
        part = compare(
            m,
            fields[m.id],
            sheet,
            read["collections"][m.collection],
            base[m.id],
            seen_at,
            required_fields(manifest, m),
            update_conditions(manifest, m),
        )
        part["collection"] = m.collection
        part["headers"] = {c["field"]: c["header"] for c in m.columns}
        parts[str(m.id)] = part
    plan = {
        "release": read.get("release"),
        "summary": _total(list(parts.values())),
        "mappings": parts,
    }
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
) -> SheetOperation:
    link, google_user, plan = await _plan(session, settings, user, asset_id)
    return await _store(session, user, link, google_user, plan, auto=False)


# What makes an automatic preview worth a row: something to apply, or
# conflicts a person decides. Issues alone are shown by a person's preview.
_WORTH_STORING = ("imports", "exports", "creates", "appends", "conflicts")


async def auto_preview(
    session: AsyncSession,
    settings: Settings,
    owner: User,
    asset_id: UUID,
    book: Book | None = None,
) -> SheetOperation | None:
    """An automatic run's preview, stored only when it is worth a row: most
    runs find nothing to do and leave nothing behind."""
    link, google_user, plan = await _plan(session, settings, owner, asset_id, book)
    if not any(plan["summary"].get(k) for k in _WORTH_STORING):
        return None
    return await _store(session, owner, link, google_user, plan, auto=True)


# -------------------------------------------------------------------- apply


def _decide(op: SheetOperation, decisions: Mapping[str, str]) -> dict[str, Any]:
    """The app changes the decisions give, for every collection, and per
    mapping the values both sides will agree on: `local_base` once the app
    commits, `remote_base` once the sheet write is confirmed; `rows` where
    each record was seen, as [sheet_id, row in that tab]."""
    patches: list[dict[str, Any]] = []
    out: dict[str, dict[str, Any]] = {}
    undecided = []
    for mid, part in _parts(op).items():
        local_base: dict[str, dict[str, Any]] = {}
        remote_base: dict[str, dict[str, Any]] = {}
        collection = part["collection"]
        for u in part["updates"]:
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
                patches.append(
                    {
                        "op": "update",
                        "collection": collection,
                        "id": rid,
                        "revision": u["revision"],
                        "patch": patch,
                    }
                )
            local_base[rid] = {**u["same"], **patch}
            remote_base[rid] = export
        place = placer(part)
        rows = {rid: place(row) for rid, row in part["rows"].items()}
        for c in part["creates"]:
            patches.append(
                {"op": "create", "collection": collection, "id": c["record_id"], "data": c["data"]}
            )
            local_base[c["record_id"]] = dict(c["data"])
            rows[c["record_id"]] = place(c["row"])
        for c in part["converged"]:
            local_base.setdefault(c["record_id"], {}).update(c["values"])
        for a in part["appends"]:
            # Until the write is confirmed a missing row means "append again".
            local_base[a["record_id"]] = {**a["values"], UNCONFIRMED: True}
            remote_base[a["record_id"]] = {UNCONFIRMED: False}
        out[mid] = {"local_base": local_base, "remote_base": remote_base, "rows": rows}
    if undecided:
        raise InvalidInputError(
            "decisions_missing", "decide every conflict", extra={"undecided": undecided}
        )
    return {"patches": patches, "mappings": out}


async def _reserve(
    session: AsyncSession,
    settings: Settings,
    asset: Asset,
    link: SheetLink,
    mappings: list[SheetMapping],
    op: SheetOperation,
    google_user: UUID,
    decisions: Mapping[str, str],
) -> None:
    """`previewed` -> `applying`, after checking that neither the link nor the
    rows the preview touched changed and that no other sync of the file is
    applying or has a sheet write still unsettled."""
    if op.link_revision != link.revision or op.google_user_id != google_user:
        await _move(session, op.id, "previewed", state="stale")
        raise ConflictError(
            "sheet_link_changed", "the link changed since the preview; preview again"
        )
    plan = _decide(op, decisions)
    limit = await row_limit(session, settings, asset)
    token = await token_for(session, settings, grant_user_of(op))
    await session.commit()
    book = await fetch_book(token, link, mappings, limit)
    for m in mappings:
        part = _parts(op).get(str(m.id))
        if part is None or placed(part, book[str(m.id)]) is None:
            await _move(session, op.id, "previewed", state="stale")
            raise ConflictError(
                "sheet_changed", "the sheet changed since the preview; preview again"
            )
    # The link's row is locked first, so two reservations of the same file
    # queue up and the second one sees the first as busy.
    current = await session.scalar(
        select(SheetLink.revision).where(SheetLink.id == link.id).with_for_update()
    )
    if current != op.link_revision:
        await _move(session, op.id, "previewed", state="stale")
        raise ConflictError(
            "sheet_link_changed", "the link changed since the preview; preview again"
        )
    won = await session.scalar(
        update(SheetOperation)
        .where(
            SheetOperation.id == op.id,
            SheetOperation.state == "previewed",
            ~exists().where(links.busy_clause(link.id, but=op.id)),
        )
        .values(state="applying", decisions=dict(decisions), export=plan)
        .returning(SheetOperation.id)
    )
    await session.commit()
    await session.refresh(op)
    if won is None and op.state not in ("applying", "applied"):
        await links.refuse_while_busy(session, link)
        raise ConflictError("sheet_sync_in_progress", "another sync of this sheet is being applied")


async def apply(
    session: AsyncSession,
    settings: Settings,
    user: User,
    asset_id: UUID,
    op_id: UUID,
    decisions: Mapping[str, str],
) -> SheetOperation:
    asset, link, env, mappings = await runnable_link(session, user, asset_id)
    op = await operation(session, link, op_id)
    if op.actor_id != user.id:
        raise NotFoundError("sheet_operation_not_found", "no such preview of yours")
    if op.state == "previewed":
        await _reserve(
            session,
            settings,
            asset,
            link,
            mappings,
            op,
            google_user_for(link, asset, user),
            decisions,
        )
    if op.state == "applied":
        return op  # A repeated request: the outcome is already recorded.
    if op.state != "applying":
        raise ConflictError(f"sheet_operation_{op.state}", "this preview can no longer be applied")

    plan = op.export or {}
    parts = _parts(op)
    done: dict[str, Any] = {"results": []}
    if plan["patches"]:
        linked: dict[str, list[str]] = {}
        for part in parts.values():
            cols = list(part["sheet"]["cols"])
            linked[part["collection"]] = cols
        try:
            done = await call_broker(
                settings,
                f"/admin/apps/{env.asset_hex}/prod/sheets/apply",
                {
                    "user_id": str(user.id),
                    "key": str(op.id),
                    "changes": plan["patches"],
                    "fields": linked,
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
        return op  # Another request finished it meanwhile.
    created = await _created_values(session, env, mappings, parts, done["results"])
    out = {}
    for mid, own in plan["mappings"].items():
        await save_base(session, mid, own["local_base"], own["rows"])
        # A created record's own columns reach its row with the write.
        remote = dict(own["remote_base"])
        for c in parts[mid]["creates"]:
            remote[c["record_id"]] = created.get(c["record_id"], {})
        out[mid] = {**own, "remote_base": remote}
    # The automatic sync's idle shortcut no longer holds after an apply.
    await session.execute(
        update(SheetLink).where(SheetLink.id == link.id).values(auto_sheet_hash=None)
    )
    op.export = {**plan, "mappings": out, "created": created}
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
    return op


async def _created_values(
    session: AsyncSession,
    env: MicroAppEnvironment,
    mappings: list[SheetMapping],
    parts: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """The app's own columns of each created record (its defaults), for its row."""
    returned = {r["id"]: r for r in results if "values" in r}
    if not returned:
        return {}
    manifest = await links.manifest_of(session, env)
    out: dict[str, dict[str, Any]] = {}
    for m in mappings:
        part = parts.get(str(m.id))
        if part is None:
            continue
        fields = links.field_defs(manifest, m)
        app_owned = [c["field"] for c in m.columns if c["owner"] == "app" and c["field"] in fields]
        for c in part["creates"]:
            r = returned.get(c["record_id"])
            if r is not None:
                out[r["id"]] = {
                    f: values.from_app(fields[f], r["values"].get(f)) for f in app_owned
                }
    return out
