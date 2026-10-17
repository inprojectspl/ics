"""Fan-out of one asset event to every recipient and channel (ADR-0023, section 4).
Runs in the arq worker with a fixed number of queries and Redis pipelines per
event; Web Push is sent right away.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Asset, Project, PushSubscription, User
from app.services.versions import author_label
from app.util import now as utc_now

from . import inbox, recipients, schedule
from .channels import webpush
from .inbox import Delivery, Entry
from .items import AssetRef, EventKind, ProjectRef, build_payload, to_item
from .recipients import Recipient
from .render import render

logger = logging.getLogger("ics.notifications.fanout")

_PUSH_CONCURRENCY = 8
_PUSH_MAX_FAILURES = 5


@dataclass(frozen=True, slots=True)
class Delivered:
    recipient: Recipient
    entry_id: str
    payload: dict


async def _refs(
    session: AsyncSession, project_id: UUID | None, actor_id: UUID | None
) -> tuple[ProjectRef | None, str | None]:
    """Shown project and actor name in one round trip."""
    if project_id is None and actor_id is None:
        return None, None

    def project(col):
        return select(col).where(Project.id == project_id).scalar_subquery()

    def actor(col):
        return select(col).where(User.id == actor_id).scalar_subquery()

    slug, name, display_name, email = (
        await session.execute(
            select(
                project(Project.slug),
                project(Project.name),
                actor(User.display_name),
                actor(User.email),
            )
        )
    ).one()
    ref = ProjectRef(slug=slug, name=name) if slug is not None else None
    return ref, author_label(display_name, email)


async def _actor_names(session: AsyncSession, ids: Collection[UUID]) -> dict[UUID, str]:
    rows = await session.execute(
        select(User.id, User.display_name, User.email).where(User.id.in_(list(ids)))
    )
    return {i: author_label(name, email) or "" for i, name, email in rows}


async def fan_out(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    code: EventKind,
    asset_id: UUID,
    actor_id: UUID | None,
    excluded: Collection[UUID] = (),
    project_id: UUID | None = None,
    version: int | None = None,
    from_version: int | None = None,
    co_actors: Sequence[UUID] = (),
) -> int:
    """Deliver one event; returns the number of recipients. `excluded` are
    the users who caused it (they do not need to hear about it). `co_actors`,
    most recent first, are everyone who wrote in a merged burst: each reader
    sees them named, minus themselves."""
    started = time.monotonic()
    asset = await session.get(Asset, asset_id)
    if asset is None:
        return 0
    new_in_project = code in ("asset.created", "asset.added") and project_id is not None
    target_projects = (
        [project_id]
        if new_in_project and project_id is not None
        else await recipients.asset_project_ids(session, asset)
    )
    explicit = await recipients.watchers(session, asset, code, target_projects)
    own = recipients.owners(asset, code)
    candidates = (explicit | own) - set(excluded)
    readers = [
        r
        for r in await recipients.readable(session, asset, candidates)
        if r.prefs.enabled and (r.id in explicit or r.prefs.watch_own_assets)
    ]
    if not readers:
        return 0

    project, actor_name = await _refs(
        session, project_id if new_in_project else asset.project_id, actor_id
    )
    asset_ref = AssetRef(
        id=str(asset.id), slug=asset.slug, title=asset.title or asset.slug, kind=asset.kind
    )
    count = 1 if from_version is None or version is None else max(1, version - from_version + 1)

    def payload_for(actors: Sequence[UUID], name: str | None) -> dict:
        return build_payload(
            code,
            asset=asset_ref,
            project=project,
            actor_id=str(actors[0]) if actors else None,
            actor_name=name,
            actor_count=len(actors),
            version=version,
            from_version=from_version,
            count=count,
        )

    if co_actors:
        names = await _actor_names(session, co_actors)
        targets = []
        for r in readers:
            others = [a for a in co_actors if a != r.id and a in names]
            targets.append((r, payload_for(others, ", ".join(names[a] for a in others))))
    else:
        single = payload_for([actor_id] if actor_id else [], actor_name)
        targets = [(r, single) for r in readers]
    collapse = f"{code}:{asset.id}" if code == "asset.updated" else None
    delivered = await deliver(redis, settings, targets, collapse=collapse)
    await _route_channels(session, redis, settings, code, delivered)
    logger.info(
        "notify.fanout code=%s asset=%s recipients=%d ms=%d",
        code,
        asset.id,
        len(delivered),
        int((time.monotonic() - started) * 1000),
    )
    return len(delivered)


async def deliver(
    redis: Redis,
    settings: Settings,
    targets: list[tuple[Recipient, dict]],
    *,
    collapse: str | None = None,
) -> list[Delivered]:
    """Write to the inboxes and publish live events."""
    results = await inbox.push_many(
        redis,
        [Delivery(user_id=r.id, payload=p, collapse=collapse) for r, p in targets],
        settings,
    )
    pipe = redis.pipeline(transaction=False)
    out: list[Delivered] = []
    for (recipient, payload), (entry_id, unread) in zip(targets, results, strict=True):
        item = to_item(Entry(id=entry_id, payload=payload, read=False))
        pipe.publish(
            inbox.live_channel(recipient.id),
            inbox.live_message("notification", {"item": item, "unread": unread}, entry_id=entry_id),
        )
        out.append(Delivered(recipient=recipient, entry_id=entry_id, payload=payload))
    await pipe.execute()
    return out


async def _route_channels(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    kind: EventKind,
    delivered: list[Delivered],
) -> None:
    push_targets: list[Delivered] = []
    batched: list[schedule.BatchItem] = []
    now = time.time()
    for d in delivered:
        p = d.recipient.prefs
        if settings.smtp_host and p.wants(kind, "email"):
            due = (
                schedule.next_digest_at(settings)
                if p.email_mode == "daily"
                else now + settings.notifications_email_batch_seconds
            )
            batched.append(schedule.BatchItem(d.recipient.id, "mail", d.entry_id, due))
        if p.wants(kind, "chat"):
            due = now + settings.notifications_chat_batch_seconds
            batched.append(schedule.BatchItem(d.recipient.id, "chat", d.entry_id, due))
        if p.wants(kind, "push"):
            push_targets.append(d)
    await schedule.add_to_batches(redis, batched, settings)
    if push_targets and webpush.is_configured(settings):
        await send_push(session, settings, push_targets)


async def send_push(session: AsyncSession, settings: Settings, targets: list[Delivered]) -> None:
    by_user = {d.recipient.id: d for d in targets}
    subs = (
        await session.scalars(
            select(PushSubscription).where(PushSubscription.user_id.in_(list(by_user)))
        )
    ).all()
    if not subs:
        return
    semaphore = asyncio.Semaphore(_PUSH_CONCURRENCY)
    # One text per recipient, however many devices they have.
    texts = {
        uid: render(d.entry_id, d.payload, d.recipient.locale, settings)
        for uid, d in by_user.items()
    }

    client = webpush.client()

    async def one(sub: PushSubscription) -> tuple[UUID, str]:
        r = texts[sub.user_id]
        message = {"title": r.title, "body": r.body, "url": r.url, "tag": r.tag}
        target = webpush.PushTarget(endpoint=sub.endpoint, p256dh=sub.p256dh, auth=sub.auth)
        async with semaphore:
            result = await webpush.send(client, target, message, settings=settings)
        return sub.id, result

    outcomes = await asyncio.gather(*(one(s) for s in subs))
    gone = [sid for sid, res in outcomes if res == "gone"]
    ok = [sid for sid, res in outcomes if res == "ok"]
    failed = [sid for sid, res in outcomes if res == "failed"]
    if gone:
        await session.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
    if ok:
        await session.execute(
            update(PushSubscription)
            .where(PushSubscription.id.in_(ok))
            .values(last_success_at=utc_now(), failures=0)
        )
    if failed:
        await session.execute(
            update(PushSubscription)
            .where(PushSubscription.id.in_(failed))
            .values(failures=PushSubscription.failures + 1)
        )
        await session.execute(
            delete(PushSubscription).where(
                PushSubscription.id.in_(failed), PushSubscription.failures >= _PUSH_MAX_FAILURES
            )
        )
    await session.commit()
