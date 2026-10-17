"""Who is notified about an asset event (ADR-0023, sections 3 and 4): watchers
and owners who can still read the asset. `readers_filter` mirrors
`permissions.visible_assets_filter` for users; `tests/test_notify_fanout.py`
checks it against `permissions.effective_role`.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, except_, false, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import (
    Asset,
    AssetProjectShare,
    AssetShare,
    NotificationPreference,
    ProjectMember,
    User,
    Watch,
)

from . import preferences
from .items import EventKind
from .preferences import Prefs


@dataclass(frozen=True, slots=True)
class Recipient:
    id: UUID
    locale: str | None
    prefs: Prefs


def readers_filter(asset: Asset) -> ColumnElement[bool]:
    """Users who can read `asset`, ignoring soft deletion (a deletion notice
    goes to those who could read it)."""
    pm = aliased(ProjectMember)
    ash = aliased(AssetShare)
    aps = aliased(AssetProjectShare)
    pm2 = aliased(ProjectMember)
    home_member = (
        select(pm.id)
        .where(
            pm.project_id == asset.project_id,
            pm.user_id == User.id,
            pm.accepted_at.is_not(None),
        )
        .exists()
        if asset.project_id is not None
        else false()
    )
    return or_(
        User.role == "admin",
        User.id == asset.owner_id,
        home_member,
        select(ash.id).where(ash.asset_id == asset.id, ash.user_id == User.id).exists(),
        select(aps.asset_id)
        .join(pm2, pm2.project_id == aps.project_id)
        .where(
            aps.asset_id == asset.id,
            pm2.user_id == User.id,
            pm2.accepted_at.is_not(None),
        )
        .exists(),
    )


async def asset_project_ids(session: AsyncSession, asset: Asset) -> list[UUID]:
    """Home project plus the projects the asset is shared into (ADR-0017)."""
    shared = await session.scalars(
        select(AssetProjectShare.project_id).where(AssetProjectShare.asset_id == asset.id)
    )
    ids = [asset.project_id] if asset.project_id is not None else []
    return ids + [p for p in shared if p not in ids]


async def watchers(
    session: AsyncSession, asset: Asset, kind: EventKind, project_ids: Collection[UUID]
) -> set[UUID]:
    """Explicit watchers for the event, minus those who muted the asset."""
    parts = []
    if kind in ("asset.updated", "asset.deleted"):
        parts.append(
            select(Watch.user_id).where(Watch.asset_id == asset.id, Watch.level == "watch")
        )
    if project_ids and kind != "asset.deleted":
        levels = ("all",) if kind == "asset.updated" else ("new", "all")
        parts.append(
            select(Watch.user_id).where(
                Watch.project_id.in_(list(project_ids)), Watch.level.in_(levels)
            )
        )
    if not parts:
        return set()
    muted = select(Watch.user_id).where(Watch.asset_id == asset.id, Watch.level == "mute")
    return set((await session.scalars(except_(union(*parts), muted))).all())


def owners(asset: Asset, kind: EventKind) -> set[UUID]:
    """Owner and maintainer hear about others' changes to their assets
    (subject to `watch_own_assets`)."""
    if kind not in ("asset.updated", "asset.deleted"):
        return set()
    return {u for u in (asset.owner_id, asset.maintainer_id) if u is not None}


async def readable(
    session: AsyncSession, asset: Asset, user_ids: Collection[UUID]
) -> list[Recipient]:
    """Candidates who can read the asset, with their preferences, in one query."""
    if not user_ids:
        return []
    rows = await session.execute(
        select(User.id, User.locale, NotificationPreference)
        .outerjoin(NotificationPreference, NotificationPreference.user_id == User.id)
        .where(User.id.in_(list(user_ids)), readers_filter(asset))
    )
    return [
        Recipient(id=uid, locale=locale, prefs=preferences.from_row(row))
        for uid, locale, row in rows.tuples()
    ]
