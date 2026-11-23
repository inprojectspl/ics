"""Automatic syncs of sheet links (ADR-0031, ADR-0032).

A link with `auto_sync` is synced by ICS itself, as the asset owner on the
owner's Google account, through the same preview and apply a person runs.
What brings a run is the app's activity, as the broker reports it every 10
seconds and a sweeper reads it from the platform database: a write to the
linked collection (recorded on the link as `app_changed_at`) syncs at the
next sweep; while people have the app open the sheet is read every
`google_sheets_active_poll_seconds`, while it is awake every
`google_sheets_poll_seconds`; a sleeping or suspended app is left alone, so
waking up after a sleep longer than the interval (or a read of its data
through ICS) syncs at once. A run whose sheet is as the last idle run found
it, with no app change since, reads only Google. A preview with conflicts
is left for a person, and so is any error that a retry would not fix; the
owner hears of both once, in the inbox.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.domain_errors import DomainError
from app.models import Asset, MicroAppEnvironment, MicroAppStats, SheetLink, SheetOperation, User
from app.redis_client import get_redis
from app.services.micro_applications import status
from app.services.micro_applications.common import ENVIRONMENT
from app.services.notifications import preferences
from app.services.notifications.fanout import notify_user
from app.services.notifications.items import AssetRef, build_payload

from . import grants, sync
from .compare import Sheet

log = structlog.get_logger(__name__)

# A preview a person made is theirs to apply for this long; an automatic run
# would supersede it.
HELD_FOR = timedelta(minutes=10)
# Errors the next run may not see again: they neither stop nor notify.
_PASSING = frozenset(
    {
        "broker_unavailable",
        "google_unavailable",
        "google_rate_limited",
        "app_changed",
        "sheet_changed",
        "sheet_link_changed",
        "sheet_link_applying",
        "release_changed",
        "sheet_operation_superseded",
    }
)


async def _waiting(session: AsyncSession, link: SheetLink, now: datetime) -> bool:
    """A preview waits for a person: one with conflicts, or a fresh one of theirs."""
    found = await session.scalar(
        select(SheetOperation.id)
        .where(
            SheetOperation.link_id == link.id,
            SheetOperation.state == "previewed",
            or_(
                and_(SheetOperation.auto.is_(False), SheetOperation.created_at > now - HELD_FOR),
                and_(
                    SheetOperation.auto.is_(True),
                    SheetOperation.summary["conflicts"].as_integer() > 0,
                ),
            ),
        )
        .limit(1)
    )
    return found is not None


async def _tell_owner(
    session: AsyncSession, settings: Settings, asset: Asset, owner: User, reason: str, n: int
) -> None:
    payload = build_payload(
        "sheets.auto_sync_stopped",
        asset=AssetRef(
            id=str(asset.id), slug=asset.slug, title=asset.title or asset.slug, kind=asset.kind
        ),
        project=None,
        actor_id=None,
        actor_name=None,
        params={"reason": reason, "conflicts": n},
    )
    prefs = await preferences.load(session, owner.id)
    await notify_user(get_redis(), settings, owner, prefs, payload)


# Sweeps come every 10 seconds; no link runs more often than that.
FLOOR = timedelta(seconds=10)


def _seconds(value: int) -> timedelta:
    return max(timedelta(seconds=value), FLOOR)


def _poll(settings: Settings) -> timedelta:
    return _seconds(settings.google_sheets_poll_seconds)


def _due(
    now: datetime,
    interval: timedelta | None,
    checked_at: datetime | None,
    next_at: datetime | None,
    app_changed_at: datetime | None,
) -> bool:
    """Whether a link runs now: not before `next_at` nor within FLOOR of the
    last run; then when the app changed since that run, or the run is older
    than `interval` (None: the app sleeps, only its changes count)."""
    if next_at is not None and now < next_at:
        return False
    if checked_at is None:
        return interval is not None or app_changed_at is not None
    if now - checked_at < FLOOR:
        return False
    if app_changed_at is not None and app_changed_at > checked_at:
        return True
    return interval is not None and now - checked_at >= interval


def _sheet_hash(sheet: Sheet, revision: int, release: UUID | None) -> str:
    """The linked columns as read, under this link and release."""
    raw = json.dumps(
        [
            revision,
            str(release),
            sheet.sheet_id,
            sheet.tz,
            sheet.header,
            sheet.rows,
            sorted(sheet.duplicates),
        ],
        default=str,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


async def run(session: AsyncSession, settings: Settings, link_id: UUID) -> str:
    """One sync of one link, when its turn came; what happened, for the log."""
    link = await session.get(SheetLink, link_id)
    if link is None or not link.auto_sync or link.paused:
        return "off"
    asset = await session.get(Asset, link.asset_id)
    owner = await session.get(User, asset.owner_id) if asset else None
    if asset is None or owner is None or owner.is_locked:
        return "off"
    now = datetime.now(UTC)
    checked_at, next_at = link.auto_checked_at, link.auto_next_at
    app_changed = link.app_changed_at is not None and (
        checked_at is None or link.app_changed_at > checked_at
    )
    # Queued twice, or by a read of the app's data: the last run stands.
    if not _due(now, FLOOR, checked_at, next_at, link.app_changed_at):
        return "held"
    if await _waiting(session, link, now):
        await _record(session, link_id, auto_checked_at=now, auto_next_at=now + _poll(settings))
        return "waiting"

    error: str | None = None
    conflicts = 0
    outcome = "synced"
    digest: str | None = None
    try:
        sheet = await sync.linked_sheet(session, settings, owner, asset.id)
        release = await session.scalar(
            select(MicroAppEnvironment.active_release_id).where(
                MicroAppEnvironment.asset_id == asset.id,
                MicroAppEnvironment.environment == ENVIRONMENT,
            )
        )
        digest = _sheet_hash(sheet, link.revision, release)
        if digest == link.auto_sheet_hash and not app_changed:
            # Neither side moved since a run that found nothing to do.
            op, outcome = None, "idle"
        else:
            op = await sync.auto_preview(session, settings, owner, asset.id, sheet)
        conflicts = int((op.summary or {}).get("conflicts") or 0) if op else 0
        if op is None:
            outcome = "idle"
        elif conflicts:
            error, outcome = "conflicts", "conflicts"
        else:
            await sync.apply(session, settings, owner, asset.id, op.id, {})
    except DomainError as e:
        error = e.code
    if error in _PASSING:
        # Back off: 10 s, then twice the previous delay, up to the poll interval.
        last = next_at - checked_at if next_at and checked_at and next_at > checked_at else None
        delay = min(2 * last, _poll(settings)) if last else FLOOR
        await _record(
            session, link_id, auto_checked_at=now, auto_next_at=now + delay, auto_sheet_hash=None
        )
        log.info("sheets_auto_retry", link_id=str(link_id), code=error)
        return "retry"

    link = await session.get(SheetLink, link_id, populate_existing=True)
    if link is None:
        return "off"
    if error and error != link.auto_error:
        await _tell_owner(session, settings, asset, owner, error, conflicts)
    link.auto_error = error
    link.auto_checked_at = now
    # After a stop only the poll interval brings another try.
    link.auto_next_at = now + _poll(settings) if error else None
    # Kept only when a full look found nothing to do: an apply changed the
    # sheet (or failed to), so the next run compares again.
    link.auto_sheet_hash = digest if outcome == "idle" and not error else None
    await session.commit()
    if error:
        log.info("sheets_auto_stopped", link_id=str(link_id), code=error)
        return "stopped"
    return outcome


async def _record(session: AsyncSession, link_id: UUID, **values: Any) -> None:
    await session.execute(update(SheetLink).where(SheetLink.id == link_id).values(**values))
    await session.commit()


# ------------------------------------------------------------- when to run


def _interval(settings: Settings, runtime: dict[str, Any]) -> timedelta | None:
    """How often the sheet is read now, by the app's runtime as the panel
    shows it (`status.runtime_view`); None while the app sleeps."""
    if runtime["state"] in ("suspended", "draining"):
        return None
    if runtime["realtime"]["sockets"]:
        return _seconds(settings.google_sheets_active_poll_seconds)
    if runtime["state"] in status.AWAKE_STATES:
        return _poll(settings)
    return None


async def due_links(session: AsyncSession, settings: Settings) -> list[UUID]:
    """Links whose sync is due by the app's activity, in one query; writes
    nothing."""
    now = datetime.now(UTC)
    broker = await status.broker_incarnation()
    rows = (
        await session.execute(
            select(
                SheetLink.id,
                SheetLink.auto_checked_at,
                SheetLink.auto_next_at,
                SheetLink.app_changed_at,
                MicroAppEnvironment,
                MicroAppStats,
            )
            .join(
                MicroAppEnvironment,
                and_(
                    MicroAppEnvironment.asset_id == SheetLink.asset_id,
                    MicroAppEnvironment.environment == ENVIRONMENT,
                ),
            )
            .outerjoin(MicroAppStats, MicroAppStats.environment_id == MicroAppEnvironment.id)
            .where(SheetLink.auto_sync.is_(True), SheetLink.paused.is_(False))
        )
    ).all()
    return [
        r.id
        for r in rows
        if _due(
            now,
            _interval(settings, status.runtime_view(r[4], r[5], broker)),
            r.auto_checked_at,
            r.auto_next_at,
            r.app_changed_at,
        )
    ]


async def read_links(session: AsyncSession, settings: Settings, asset_id: UUID) -> list[UUID]:
    """A read of the app's data through ICS counts as a wake-up: the link
    syncs unless it was looked at within the poll interval."""
    if not grants.enabled(settings):
        return []
    now = datetime.now(UTC)
    rows = await session.execute(
        select(
            SheetLink.id,
            SheetLink.auto_checked_at,
            SheetLink.auto_next_at,
            SheetLink.app_changed_at,
        ).where(
            SheetLink.asset_id == asset_id,
            SheetLink.auto_sync.is_(True),
            SheetLink.paused.is_(False),
        )
    )
    return [
        r.id
        for r in rows
        if _due(now, _poll(settings), r.auto_checked_at, r.auto_next_at, r.app_changed_at)
    ]


async def enqueue(pool: Any, settings: Settings, link_ids: list[UUID]) -> int:
    """Queue a run per link on the sheets queue. The job id keeps one run per
    link queued or running; the job keeps no result, so the id is free again
    as soon as a run ends."""
    for link_id in link_ids:
        await pool.enqueue_job(
            "sheets_auto_sync",
            str(link_id),
            _job_id=f"sheets-auto:{link_id}",
            _queue_name=settings.google_sheets_queue_name,
        )
    return len(link_ids)


async def enqueue_soon(settings: Settings, link_ids: list[UUID]) -> None:
    """`enqueue` from a request: a lost enqueue only delays the sync to the
    next sweep, so it never fails the request."""
    if not link_ids:
        return
    from app.jobs.queue import get_pool

    try:
        await enqueue(await get_pool(), settings, link_ids)
    except Exception:
        log.warning("sheets_auto_enqueue_failed", links=len(link_ids), exc_info=True)
