"""Producers' entry point: `emit_*` after the write is committed.

Best effort by design (ADR-0023, section 4): a failure here is logged and
never fails the request that changed the asset.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Asset, Project, ProjectMember, User
from app.redis_client import get_redis
from app.services.versions import author_label

from . import preferences, schedule
from .fanout import notify_user
from .items import EventKind, ProjectRef, build_payload

logger = logging.getLogger("ics.notifications.events")

EVENT_FUNCTION = "notify_asset_event"


def _actor_id(actor: User | UUID | None) -> UUID | None:
    return actor.id if isinstance(actor, User) else actor


async def _enqueue(
    code: EventKind, asset_id: UUID, actor_id: UUID | None, project_id: UUID | None
) -> None:
    from app.jobs.queue import enqueue  # request paths that never emit skip the pool

    try:
        await enqueue(
            EVENT_FUNCTION,
            code,
            str(asset_id),
            str(actor_id) if actor_id else None,
            str(project_id) if project_id else None,
        )
    except Exception as e:
        logger.warning("notify emit failed: code=%s asset=%s err=%s", code, asset_id, e)


async def emit_created(asset: Asset, actor: User | UUID | None) -> None:
    """A new asset; only project watchers can hear about it."""
    if asset.project_id is not None:
        await _enqueue("asset.created", asset.id, _actor_id(actor), asset.project_id)


async def emit_added(asset: Asset, project_id: UUID, actor: User | UUID | None) -> None:
    """An existing asset moved or shared into `project_id`."""
    await _enqueue("asset.added", asset.id, _actor_id(actor), project_id)


async def emit_deleted(asset: Asset, actor: User | UUID | None) -> None:
    await _enqueue("asset.deleted", asset.id, _actor_id(actor), None)


async def emit_updated(
    asset: Asset, version: int, actor: User | UUID | None, settings: Settings
) -> None:
    """A new version; bursts are merged by the due queue (`schedule.py`)."""
    try:
        await schedule.note_update(get_redis(), asset.id, version, _actor_id(actor), settings)
    except Exception as e:
        logger.warning("notify emit failed: code=asset.updated asset=%s err=%s", asset.id, e)


async def emit_invited(
    session: AsyncSession,
    settings: Settings,
    member: ProjectMember,
    project: Project,
    inviter: User,
    invitee: User,
) -> None:
    """A project invitation in the invitee's inbox, next to its e-mail; the
    entry opens the acceptance screen. Delivered here, not through the
    worker: one known recipient needs no fan-out query."""
    try:
        payload = build_payload(
            "project.invited",
            asset=None,
            project=ProjectRef(slug=project.slug, name=project.name),
            actor_id=str(inviter.id),
            actor_name=author_label(inviter.display_name, inviter.email),
            params={"role": member.role},
        )
        prefs = await preferences.load(session, invitee.id)
        await notify_user(get_redis(), settings, invitee, prefs, payload)
    except Exception as e:
        logger.warning("notify emit failed: code=project.invited user=%s err=%s", invitee.id, e)
