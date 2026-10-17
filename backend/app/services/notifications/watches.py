"""Watches of assets and projects (ADR-0023, section 2). Access is checked by
the routes; this module only reads and writes the rows."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, NotificationPreference, Project, Watch

from .preferences import DEFAULT_PREFS

AssetLevel = Literal["watch", "mute"]
ProjectLevel = Literal["new", "all"]


async def _upsert(
    session: AsyncSession, user_id: UUID, column: str, target: UUID, level: str
) -> None:
    await session.execute(
        pg_insert(Watch)
        .values(user_id=user_id, level=level, **{column: target})
        .on_conflict_do_update(
            index_elements=[Watch.user_id, getattr(Watch, column)],
            index_where=text(f"{column} IS NOT NULL"),
            set_={"level": level},
        )
    )


async def set_asset(
    session: AsyncSession, user_id: UUID, asset_id: UUID, level: AssetLevel
) -> None:
    await _upsert(session, user_id, "asset_id", asset_id, level)


async def set_project(
    session: AsyncSession, user_id: UUID, project_id: UUID, level: ProjectLevel
) -> None:
    await _upsert(session, user_id, "project_id", project_id, level)


async def clear_asset(session: AsyncSession, user_id: UUID, asset_id: UUID) -> None:
    await session.execute(delete(Watch).where(Watch.user_id == user_id, Watch.asset_id == asset_id))


async def clear_project(session: AsyncSession, user_id: UUID, project_id: UUID) -> None:
    await session.execute(
        delete(Watch).where(Watch.user_id == user_id, Watch.project_id == project_id)
    )


async def project_level(session: AsyncSession, user_id: UUID, project_id: UUID) -> str | None:
    return await session.scalar(
        select(Watch.level).where(Watch.user_id == user_id, Watch.project_id == project_id)
    )


async def asset_state(session: AsyncSession, user_id: UUID, asset: Asset) -> dict[str, Any]:
    """The asset's own watch, its project's watch and the own-assets
    preference, in one round trip."""
    own_level = select(Watch.level).where(Watch.user_id == user_id, Watch.asset_id == asset.id)
    project_watch = select(Watch.level).where(
        Watch.user_id == user_id, Watch.project_id == asset.project_id
    )
    own_pref = select(NotificationPreference.watch_own_assets).where(
        NotificationPreference.user_id == user_id
    )
    level, via, watch_own = (
        await session.execute(
            select(
                own_level.scalar_subquery(),
                project_watch.scalar_subquery(),
                own_pref.scalar_subquery(),
            )
        )
    ).one()
    is_owner = user_id in (asset.owner_id, asset.maintainer_id)
    own = is_owner and (watch_own if watch_own is not None else DEFAULT_PREFS.watch_own_assets)
    return {"level": level, "via_project": via, "own": own}


async def list_for_user(
    session: AsyncSession, user_id: UUID, *, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    """Watched items, newest first, with the total in the same query.
    Soft-deleted targets are hidden."""
    live = or_(
        and_(Watch.asset_id.is_not(None), Asset.deleted_at.is_(None)),
        and_(Watch.project_id.is_not(None), Project.deleted_at.is_(None)),
    )
    rows = (
        (
            await session.execute(
                select(Watch, Asset, Project, func.count().over().label("total"))
                .outerjoin(Asset, Asset.id == Watch.asset_id)
                .outerjoin(Project, Project.id == Watch.project_id)
                .where(Watch.user_id == user_id, live)
                .order_by(Watch.created_at.desc(), Watch.id)
                .limit(limit)
                .offset(offset)
            )
        )
        .tuples()
        .all()
    )
    items: list[dict[str, Any]] = []
    for watch, asset, project, _ in rows:
        item: dict[str, Any] = {"level": watch.level, "created_at": watch.created_at.isoformat()}
        if asset is not None:
            item["type"] = "asset"
            item["asset"] = {
                "id": str(asset.id),
                "slug": asset.slug,
                "title": asset.title or asset.slug,
                "kind": asset.kind,
            }
        elif project is not None:
            item["type"] = "project"
            item["project"] = {"slug": project.slug, "name": project.name}
        items.append(item)
    return items, (int(rows[0][3]) if rows else 0)
