"""Project CRUD: list, create, get, patch, delete."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import CurrentUser
from app.db import get_session
from app.models import Asset, AssetPin, Project, ProjectMember, User
from app.services import asset_lifecycle
from app.services import project_links as project_links_svc
from app.services import project_shares as project_shares_svc
from app.services.asset_lifecycle import ArchiveView
from app.services.asset_listing import build_asset_summaries
from app.services.asset_sort import AssetSortKey, SortOrder, asset_order_by
from app.slug import generate_slug

from ._models import CreateProjectIn, PatchProjectIn
from ._router import router
from ._shared import (
    _bulk_counts,
    _count_assets,
    _count_members,
    _member_row,
    _project_row,
    _project_with_min_role,
    _utcnow,
)

# Capped; `assets_truncated` tells the client the list is cut.
ASSETS_PAGE_LIMIT = 200


@router.get("")
async def list_projects(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 25,
) -> dict:
    """Paginated list of projects the caller can see.

    Regular users: projects where they're an accepted member.
    System admins: all non-deleted projects.
    """
    offset = (page - 1) * page_size

    if user.acts_as_admin:
        base = select(Project).where(Project.deleted_at.is_(None))
        total = int(
            (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
        )
        projects = (
            (
                await session.execute(
                    base.order_by(Project.created_at.desc()).limit(page_size).offset(offset)
                )
            )
            .scalars()
            .all()
        )
        project_ids = [p.id for p in projects]
        members_by_pid, assets_by_pid = await _bulk_counts(session, project_ids)
        # Admin's role per-project: single SELECT for memberships of this user
        # across the page.
        my_roles: dict[UUID, str] = {}
        if project_ids:
            rows = (
                await session.execute(
                    select(ProjectMember.project_id, ProjectMember.role).where(
                        ProjectMember.project_id.in_(project_ids),
                        ProjectMember.user_id == user.id,
                        ProjectMember.accepted_at.is_not(None),
                    )
                )
            ).all()
            my_roles = {pid: r for pid, r in rows}
        items = [
            _project_row(
                p,
                my_role=my_roles.get(p.id),
                member_count=members_by_pid.get(p.id, 0),
                asset_count=assets_by_pid.get(p.id, 0),
            )
            for p in projects
        ]
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    base_pairs = (
        select(Project, ProjectMember)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .where(
            ProjectMember.user_id == user.id,
            ProjectMember.accepted_at.is_not(None),
            Project.deleted_at.is_(None),
        )
    )
    total = int(
        (
            await session.execute(select(func.count()).select_from(base_pairs.subquery()))
        ).scalar_one()
    )
    pairs = (
        await session.execute(
            base_pairs.order_by(Project.created_at.desc()).limit(page_size).offset(offset)
        )
    ).all()
    project_ids = [p.id for p, _ in pairs]
    members_by_pid, assets_by_pid = await _bulk_counts(session, project_ids)
    items = [
        _project_row(
            p,
            my_role=m.role,
            member_count=members_by_pid.get(p.id, 0),
            asset_count=assets_by_pid.get(p.id, 0),
        )
        for p, m in pairs
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(
    body: CreateProjectIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    project = Project(
        slug=generate_slug(10),
        name=body.name,  # DTO already trims + rejects blank
        description=body.description,
        created_by=user.id,
    )
    session.add(project)
    await session.flush()
    owner_member = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role="owner",
        invited_by=user.id,
        accepted_at=_utcnow(),
    )
    session.add(owner_member)
    await audit.record(
        session,
        actor=user,
        action="project_created",
        target=f"project:{project.id}",
        payload={"slug": project.slug, "name": project.name},
    )
    await session.commit()
    await session.refresh(project)
    return _project_row(project, my_role="owner", member_count=1, asset_count=0)


async def _member_rows(session: AsyncSession, project: Project) -> list:
    return list(
        (
            await session.execute(
                select(ProjectMember, User)
                .join(User, User.id == ProjectMember.user_id)
                .where(ProjectMember.project_id == project.id)
                .order_by(ProjectMember.invited_at.asc())
            )
        ).all()
    )


@router.get("/{slug}/members")
async def list_members(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """The project's people without its documents, for clients that only ask
    who belongs to it (ics-mcp)."""
    project, my_role = await _project_with_min_role(session, slug, user, "viewer")
    rows = await _member_rows(session, project)
    return {
        "slug": project.slug,
        "name": project.name,
        "my_role": my_role,
        "member_count": sum(1 for m, _ in rows if m.accepted_at is not None),
        "members": [_member_row(m, user=u) for m, u in rows],
    }


@router.get("/{slug}")
async def get_project(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    sort: Annotated[AssetSortKey, Query()] = "updated",
    order: Annotated[SortOrder | None, Query()] = None,
    archive: Annotated[
        ArchiveView,
        Query(description="`active` (default) leaves the project's archive out."),
    ] = "active",
) -> dict:
    project, my_role = await _project_with_min_role(session, slug, user, "viewer")
    members_rows = await _member_rows(session, project)
    members = [_member_row(m, user=u) for m, u in members_rows]
    in_project = project_shares_svc.in_project_filter(project.id)
    # The header counts the project's active documents and the filter offers
    # the archive by its size, whatever the current view.
    active_count, archived_count = (
        await session.execute(
            select(
                func.count(Asset.id).filter(asset_lifecycle.archive_predicate("active")),
                func.count(Asset.id).filter(asset_lifecycle.archive_predicate("archived")),
            ).where(in_project, *asset_lifecycle.listed("all"))
        )
    ).one()
    listed_total = {
        "active": active_count,
        "archived": archived_count,
        "all": active_count + archived_count,
    }[archive]
    # Pins are per user, so join the caller's own.
    asset_rows = (
        await session.execute(
            select(Asset, AssetPin.pinned_at)
            .outerjoin(AssetPin, AssetPin.for_user(user.id))
            .where(in_project, *asset_lifecycle.listed(archive))
            .order_by(*asset_order_by(sort, order))
            .limit(ASSETS_PAGE_LIMIT)
        )
    ).all()
    assets = [a for a, _ in asset_rows]
    pin_at_by_asset = {a.id: p for a, p in asset_rows}
    # Full AssetSummary rows (my_role, share modes, owner, binding...) so the
    # project file list renders with the same component as the home view.
    asset_list = await build_asset_summaries(
        session,
        user,
        assets,
        pin_at_by_asset=pin_at_by_asset,
    )
    # Assets assigned from another home project carry a marker (ADR-0017).
    for row in asset_list:
        row["shared_in"] = row["project_id"] != str(project.id)
    return {
        **_project_row(
            project,
            my_role=my_role,
            member_count=sum(1 for m, _ in members_rows if m.accepted_at is not None),
            asset_count=int(active_count),
        ),
        "members": members,
        "assets": asset_list,
        "assets_truncated": listed_total > len(asset_list),
        "archived_count": int(archived_count),
    }


@router.patch("/{slug}")
async def patch_project(
    slug: str,
    body: PatchProjectIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    project, _ = await _project_with_min_role(session, slug, user, "owner")
    changed = []
    if body.name is not None and body.name != project.name:
        project.name = body.name  # DTO already trims + rejects blank
        changed.append("name")
    if body.description is not None and body.description != project.description:
        project.description = body.description
        changed.append("description")
    if changed:
        await audit.record(
            session,
            actor=user,
            action="project_updated",
            target=f"project:{project.id}",
            payload={"fields": changed},
        )
        await session.commit()
        await session.refresh(project)
    return _project_row(
        project,
        my_role="owner",
        member_count=await _count_members(session, project.id),
        asset_count=await _count_assets(session, project.id),
    )


@router.delete("/{slug}", status_code=status.HTTP_200_OK)
async def delete_project(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Soft-delete the project. Files inside lose `project_id` (return to
    personal vault); without this they'd be orphaned on a tombstoned
    project, hidden from every listing.
    """
    project, _ = await _project_with_min_role(session, slug, user, "owner")
    project.deleted_at = _utcnow()
    await session.execute(
        update(Asset).where(Asset.project_id == project.id).values(project_id=None)
    )
    await project_shares_svc.drop_for_project(session, project.id)
    await project_links_svc.drop_external_refs(session, project.id)
    await audit.record(
        session,
        actor=user,
        action="project_deleted",
        target=f"project:{project.id}",
        payload={"slug": project.slug, "name": project.name},
    )
    await session.commit()
    return {"deleted": True}
