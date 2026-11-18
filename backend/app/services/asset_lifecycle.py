"""Archive and trash of assets (ADR-0029).

An archived asset keeps working (links, shares, its slug) but lists and
search leave it out unless asked for. A deleted asset goes to the trash:
nobody reaches it, only its managers see it there, and the purge removes
it with its files after the retention period. Both belong to the asset's
container: its project, or the global archive and trash of its owner.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, Row, and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, quota
from app.config import Settings
from app.models import (
    Asset,
    AssetShare,
    MicroAppGrant,
    MicroAppPlan,
    ProjectMember,
    ShareLink,
    User,
)
from app.services.project_shares import in_project_filter
from app.storage import delete_prefixes, storage_from_url
from app.util import now as utc_now

ArchiveState = Literal["active", "archived"]
# What a list covers: the active assets (the default everywhere), the
# archive alone, or both.
ArchiveView = Literal["active", "archived", "all"]
_PURGE_BATCH = 50


async def _record(session: AsyncSession, request: Any, **entry: Any) -> None:
    """Audit with the client and transport of `request` when there is one."""
    if request is None:
        await audit.record(session, **entry)
    else:
        await audit.record_from_request(session, request, **entry)


def archive_predicate(state: ArchiveState, model: Any = Asset) -> ColumnElement[bool]:
    return model.archived_at.is_(None) if state == "active" else model.archived_at.is_not(None)


def listed(view: ArchiveView = "active", model: Any = Asset) -> list[ColumnElement[bool]]:
    """Assets as lists, counts, search and upkeep show them: never the
    trash, the archive only as `view` asks. Opening by link, share or slug
    does not use this: an archived asset still opens."""
    out = [model.deleted_at.is_(None)]
    if view != "all":
        out.append(archive_predicate(view, model))
    return out


def trash_filter(user: User, project_id: UUID | None = None) -> ColumnElement[bool]:
    """Assets in the trash that `user` may restore or purge: their own, and
    those of projects they own; `project_id` narrows it to one project."""
    clauses: list[ColumnElement[bool]] = [Asset.deleted_at.is_not(None)]
    if not user.acts_as_admin:
        owned_projects = select(ProjectMember.project_id).where(
            ProjectMember.user_id == user.id,
            ProjectMember.role == "owner",
            ProjectMember.accepted_at.is_not(None),
        )
        clauses.append(or_(Asset.owner_id == user.id, Asset.project_id.in_(owned_projects)))
    if project_id is not None:
        clauses.append(in_project_filter(project_id))
    return and_(*clauses)


async def set_archived(
    session: AsyncSession, user: User, asset: Asset, archived: bool, *, request: Any = None
) -> bool:
    """Archive or bring back from the archive. False when nothing changed."""
    if (asset.archived_at is not None) == archived:
        return False
    asset.archived_at = utc_now() if archived else None
    asset.archived_by = user.id if archived else None
    await _record(
        session,
        request,
        actor=user,
        action="asset_archived" if archived else "asset_unarchived",
        target=f"asset:{asset.id}",
        payload={"slug": asset.slug},
    )
    return True


async def move_to_trash(
    session: AsyncSession, settings: Settings, user: User, asset: Asset
) -> None:
    now = utc_now()
    asset.deleted_at = now
    asset.deleted_by = user.id
    asset.purge_at = now + timedelta(days=settings.trash_retention_days)
    # Soft cascade: keeps historical share IDs in the audit trail.
    await session.execute(
        update(ShareLink)
        .where(ShareLink.asset_id == asset.id, ShareLink.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    # Per-user shares and an app's roles get dropped: restoring from the
    # trash would re-create "zombie" grants the sharer might no longer want.
    await session.execute(delete(AssetShare).where(AssetShare.asset_id == asset.id))
    await session.execute(delete(MicroAppGrant).where(MicroAppGrant.asset_id == asset.id))
    await audit.record(
        session,
        actor=user,
        action="asset_deleted",
        target=f"asset:{asset.id}",
        payload={"slug": asset.slug, "kind": asset.kind},
    )


async def restore(session: AsyncSession, user: User, asset: Asset, *, request: Any = None) -> None:
    """Take an asset out of the trash. Its bytes count again against its
    owner's quota, so the owner must have room for them."""
    owner = await session.get(User, asset.owner_id)
    if owner is not None:
        await quota.assert_can_grow(
            session,
            owner.id,
            incoming_bytes=asset.size_bytes or 0,
            quota_bytes=owner.storage_quota_bytes,
        )
    asset.deleted_at = None
    asset.deleted_by = None
    asset.purge_at = None
    # The outline cache may be stale after a long absence.
    asset.outline_status = "stale"
    await _record(
        session, request, actor=user, action="asset_undeleted", target=f"asset:{asset.id}"
    )


# What the purge needs of an asset; never the whole row with its JSON.
PURGE_COLUMNS = (Asset.id, Asset.storage_prefix, Asset.kind, Asset.slug, Asset.title)


async def purge(
    session: AsyncSession,
    settings: Settings,
    rows: Sequence[Row[Any]],
    *,
    actor: User | str,
    request: Any = None,
) -> int:
    """Remove trash entries (`PURGE_COLUMNS` rows) for good, with every
    version and derived file. The read transaction ends before the files go,
    so no connection idles through the storage calls. Files go first: if this
    stops halfway, the rows stay in the trash and the next purge finishes
    them. Deleting a row cascades to versions, relations, pins and an app's
    environments, whose database schema the micro-application sweeper then
    drops. The caller commits."""
    if not rows:
        return 0
    ids = [r.id for r in rows]
    plan_prefixes = (
        await session.scalars(
            select(MicroAppPlan.storage_prefix).where(MicroAppPlan.asset_id.in_(ids))
        )
    ).all()
    await session.commit()
    prefixes = {f"{r.storage_prefix}/" for r in rows if r.storage_prefix}
    prefixes |= {f"assets/{r.id}/" for r in rows if r.kind == "micro_application"}
    prefixes |= {f"{p}/" for p in plan_prefixes if p}
    await delete_prefixes(storage_from_url(settings.storage_url), prefixes)
    await audit.record_many(
        session,
        request,
        actor=actor,
        action="asset_purged",
        entries=[
            (f"asset:{r.id}", {"slug": r.slug, "kind": r.kind, "title": r.title}) for r in rows
        ],
    )
    await session.execute(delete(Asset).where(Asset.id.in_(ids), Asset.deleted_at.is_not(None)))
    return len(ids)


async def purge_batch(
    session: AsyncSession,
    settings: Settings,
    where: ColumnElement[bool],
    *,
    limit: int,
    actor: User | str,
    request: Any = None,
) -> tuple[int, int]:
    """Purge up to `limit` trash entries matching `where`, oldest first.
    Returns (purged, left over)."""
    rows = (
        await session.execute(
            select(*PURGE_COLUMNS, func.count().over().label("total"))
            .where(where)
            .order_by(Asset.deleted_at)
            .limit(limit)
        )
    ).all()
    total = int(rows[0].total) if rows else 0
    purged = await purge(session, settings, rows, actor=actor, request=request)
    return purged, total - purged


async def purge_expired(session: AsyncSession, settings: Settings) -> int:
    """One batch of trash entries past their purge date."""
    purged, _ = await purge_batch(
        session,
        settings,
        and_(Asset.deleted_at.is_not(None), Asset.purge_at <= utc_now()),
        limit=_PURGE_BATCH,
        actor="system:trash",
    )
    return purged


async def trash_fields(session: AsyncSession, assets: Sequence[Asset]) -> dict[Any, dict]:
    """What a trash entry adds to an asset row: when it went in, who put it
    there and when it goes for good."""
    by_ids = {a.deleted_by for a in assets if a.deleted_by}
    names: dict[Any, dict] = {}
    if by_ids:
        rows = await session.execute(
            select(User.id, User.display_name, User.email).where(User.id.in_(by_ids))
        )
        names = {
            uid: {"id": str(uid), "display_name": name, "email": email}
            for uid, name, email in rows.all()
        }
    return {
        a.id: {
            "deleted_at": a.deleted_at.isoformat() if a.deleted_at else None,
            "deleted_by": names.get(a.deleted_by) if a.deleted_by else None,
            "purge_at": a.purge_at.isoformat() if a.purge_at else None,
        }
        for a in assets
    }
