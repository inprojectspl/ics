"""Shared helpers: row serializers, project lookup, count queries."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.errors import ApiError
from app.models import Asset, Project, ProjectMember, User


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


def _project_row(
    p: Project, *, my_role: str | None = None, member_count: int = 0, asset_count: int = 0
) -> dict:
    return {
        "id": str(p.id),
        "slug": p.slug,
        "name": p.name,
        "description": p.description,
        "created_by": str(p.created_by) if p.created_by else None,
        "created_at": p.created_at.isoformat(),
        "my_role": my_role,
        "member_count": member_count,
        "asset_count": asset_count,
    }


def _member_row(m: ProjectMember, *, user: User) -> dict:
    return {
        "id": str(m.id),
        "user_id": str(m.user_id),
        "email": user.email,
        "display_name": user.display_name,
        "role": m.role,
        "invited_at": m.invited_at.isoformat(),
        "accepted_at": m.accepted_at.isoformat() if m.accepted_at else None,
        "invited_by": str(m.invited_by) if m.invited_by else None,
    }


async def _get_project_by_slug(session: AsyncSession, slug: str) -> Project:
    project = (
        await session.execute(select(Project).where(Project.slug == slug))
    ).scalar_one_or_none()
    if project is None or project.deleted_at is not None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "project_not_found", "project not found")
    return project


async def _get_member(
    session: AsyncSession,
    project_id: UUID,
    user_id: UUID,
) -> ProjectMember | None:
    return (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def _project_with_min_role(
    session: AsyncSession,
    slug: str,
    user: User,
    min_role: Literal["owner", "editor", "viewer"],
) -> tuple[Project, str]:
    """Resolve project + caller's effective role; 404 if below `min_role`."""
    project = await _get_project_by_slug(session, slug)
    role = await permissions.project_role(session, user, project)
    if role is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "project_not_found", "project not found")
    rank = permissions.MEMBER_ROLE_RANK
    if rank[role] < rank[min_role]:
        # Caller is a member, so 403 is honest: it leaks no existence beyond
        # what they can already see.
        raise ApiError(
            status.HTTP_403_FORBIDDEN, "project_role_required", "insufficient project role"
        )
    return project, role


async def _count_members(session: AsyncSession, project_id: UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count(ProjectMember.id)).where(
                    ProjectMember.project_id == project_id,
                    ProjectMember.accepted_at.is_not(None),
                )
            )
        ).scalar_one()
    )


async def _count_assets(session: AsyncSession, project_id: UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count(Asset.id)).where(
                    Asset.project_id == project_id,
                    Asset.deleted_at.is_(None),
                )
            )
        ).scalar_one()
    )


async def _bulk_counts(
    session: AsyncSession,
    project_ids: list[UUID],
) -> tuple[dict[UUID, int], dict[UUID, int]]:
    """(members_by_pid, assets_by_pid) for a batch of projects; projects
    with no rows are absent, callers default to 0."""
    if not project_ids:
        return {}, {}
    member_rows = (
        await session.execute(
            select(ProjectMember.project_id, func.count(ProjectMember.id))
            .where(
                ProjectMember.project_id.in_(project_ids),
                ProjectMember.accepted_at.is_not(None),
            )
            .group_by(ProjectMember.project_id)
        )
    ).all()
    asset_rows = (
        await session.execute(
            select(Asset.project_id, func.count(Asset.id))
            .where(
                Asset.project_id.in_(project_ids),
                Asset.deleted_at.is_(None),
            )
            .group_by(Asset.project_id)
        )
    ).all()
    return (
        {pid: int(n) for pid, n in member_rows},
        {pid: int(n) for pid, n in asset_rows},
    )
