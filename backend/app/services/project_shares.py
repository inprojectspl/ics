"""Assigning an asset to projects other than its home (ADR-0017). The home keeps
ownership, quota and deletion; a share only gives another project's members a
role capped by their project role. The caller has resolved a shareable asset.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app import audit, permissions
from app.domain_errors import InvalidInputError
from app.models import Asset, AssetProjectShare, Project, User

ProjectShareRole = Literal["viewer", "editor"]


def in_project_filter(project_id: Any, entity: Any = Asset) -> ColumnElement[bool]:
    """Assets of a project: its home assets plus the ones assigned to it.
    `entity` is `Asset` or an alias of it. A UNION of two indexed lookups,
    not `project_id = X OR id IN (...)`, which the planner cannot index."""
    # Own alias: a bare `Asset` would correlate to the outer query.
    home = aliased(Asset)
    ids = (
        select(home.id)
        .where(home.project_id == project_id)
        .union(select(AssetProjectShare.asset_id).where(AssetProjectShare.project_id == project_id))
    )
    return entity.id.in_(ids)


async def list_shares(session: AsyncSession, asset: Asset) -> list[dict]:
    rows = (
        await session.execute(
            select(AssetProjectShare, Project)
            .join(Project, Project.id == AssetProjectShare.project_id)
            .where(AssetProjectShare.asset_id == asset.id, Project.deleted_at.is_(None))
            .order_by(Project.name)
        )
    ).all()
    return [
        {
            "project_id": str(share.project_id),
            "project_slug": project.slug,
            "project_name": project.name,
            "role": share.role,
            "created_at": share.created_at.isoformat() if share.created_at else None,
        }
        for share, project in rows
    ]


async def set_share(
    session: AsyncSession,
    *,
    asset: Asset,
    project_id: UUID,
    role: ProjectShareRole,
    actor: User,
) -> bool:
    """Create the share or change its role; True when the share is new. The
    actor must be able to add content to the target project, like when
    moving an asset into it."""
    if asset.project_id == project_id:
        raise InvalidInputError("project_share_home", "the asset already belongs to this project")
    await permissions.assert_project_contributor(session, actor, project_id)
    share = await session.get(AssetProjectShare, (asset.id, project_id))
    previous = share.role if share is not None else None
    if previous == role:
        return False
    if share is None:
        session.add(
            AssetProjectShare(
                asset_id=asset.id, project_id=project_id, role=role, created_by=actor.id
            )
        )
    else:
        share.role = role
    await audit.record(
        session,
        actor=actor,
        action="asset_project_share_added",
        target=f"asset:{asset.id}",
        payload={"project_id": str(project_id), "role": role, "previous_role": previous},
    )
    return share is None


async def remove_share(
    session: AsyncSession, *, asset: Asset, project_id: UUID, actor: User
) -> None:
    """Idempotent: removing a share that does not exist records nothing."""
    removed = (
        await session.execute(
            delete(AssetProjectShare)
            .where(
                AssetProjectShare.asset_id == asset.id,
                AssetProjectShare.project_id == project_id,
            )
            .returning(AssetProjectShare.role)
        )
    ).scalar_one_or_none()
    if removed is not None:
        await audit.record(
            session,
            actor=actor,
            action="asset_project_share_removed",
            target=f"asset:{asset.id}",
            payload={"project_id": str(project_id), "role": removed},
        )


async def drop_for_project(session: AsyncSession, project_id: UUID) -> None:
    """A soft-deleted project gives no access: its shares go with it."""
    await session.execute(
        delete(AssetProjectShare).where(AssetProjectShare.project_id == project_id)
    )


async def drop_for_new_home(session: AsyncSession, asset: Asset) -> None:
    """The home project cannot also be a share target."""
    if asset.project_id is not None:
        await session.execute(
            delete(AssetProjectShare).where(
                AssetProjectShare.asset_id == asset.id,
                AssetProjectShare.project_id == asset.project_id,
            )
        )
