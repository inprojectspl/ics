"""'Shared with me' tab: assets the caller reaches through project membership
or an `AssetShare` but doesn't own, grouped per project plus standalone."""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import get_session
from app.models import Asset, AssetShare, Project, ProjectMember, User

router = APIRouter(prefix="/api/shared-with-me", tags=["shared-with-me"])


def _asset_brief(a: Asset, *, owner: User | None, my_role: str) -> dict:
    return {
        "id": str(a.id),
        "slug": a.slug,
        "title": a.title,
        "kind": a.kind,
        "size_bytes": a.size_bytes,
        "updated_at": a.updated_at.isoformat(),
        "my_role": my_role,
        "owner": (
            {
                "id": str(owner.id),
                "email": owner.email,
                "display_name": owner.display_name,
            }
            if owner is not None
            else None
        ),
    }


@router.get("")
async def shared_with_me(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    # Projects the user is an accepted member of.
    project_rows = (
        await session.execute(
            select(Project, ProjectMember)
            .join(ProjectMember, ProjectMember.project_id == Project.id)
            .where(
                ProjectMember.user_id == user.id,
                ProjectMember.accepted_at.is_not(None),
                Project.deleted_at.is_(None),
            )
        )
    ).all()
    member_role_by_project: dict[UUID, str] = {p.id: m.role for p, m in project_rows}
    projects_by_id: dict[UUID, Project] = {p.id: p for p, _ in project_rows}

    # One page of assets reachable through a project or an explicit share,
    # never the caller's own. Newest first; `id` breaks ties between pages.
    shared_ids = select(AssetShare.asset_id).where(AssetShare.user_id == user.id)
    visible = (
        Asset.owner_id != user.id,
        Asset.deleted_at.is_(None),
        or_(Asset.project_id.in_(list(projects_by_id)), Asset.id.in_(shared_ids)),
    )
    total = await session.scalar(select(func.count()).select_from(Asset).where(*visible)) or 0
    page_assets = list(
        (
            await session.execute(
                select(Asset)
                .where(*visible)
                .order_by(Asset.updated_at.desc(), Asset.id.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).scalars()
    )
    project_assets = [a for a in page_assets if a.project_id in projects_by_id]

    # AssetShare entries for this page, both standalone and project-scoped.
    share_rows = (
        (
            await session.execute(
                select(AssetShare).where(
                    AssetShare.user_id == user.id,
                    AssetShare.asset_id.in_([a.id for a in page_assets]),
                )
            )
        )
        .scalars()
        .all()
        if page_assets
        else []
    )
    share_role_by_asset: dict[UUID, str] = {s.asset_id: s.role for s in share_rows}
    share_assets_by_id: dict[UUID, Asset] = {
        a.id: a for a in page_assets if a.id in share_role_by_asset
    }

    # Merge: a single asset may appear via both paths; project role wins
    # by default, but AssetShare role wins iff strictly stronger.
    rank = {"viewer": 1, "editor": 2, "owner": 3}

    def stronger(a: str | None, b: str | None) -> str:
        if a is None:
            return b or "viewer"
        if b is None:
            return a
        return a if rank[a] >= rank[b] else b

    owner_ids: set[UUID] = {a.owner_id for a in project_assets} | {
        a.owner_id for a in share_assets_by_id.values()
    }
    owners_by_id: dict[UUID, User] = {}
    if owner_ids:
        owners_by_id = {
            u.id: u
            for u in (
                await session.execute(select(User).where(User.id.in_(list(owner_ids))))
            ).scalars()
        }

    grouped: dict[UUID, list[Asset]] = defaultdict(list)
    role_per_asset: dict[UUID, str] = {}

    for a in project_assets:
        grouped[a.project_id].append(a)  # type: ignore[index]
        role_per_asset[a.id] = stronger(
            role_per_asset.get(a.id),
            member_role_by_project.get(a.project_id),  # type: ignore[arg-type]
        )

    standalone_assets: list[Asset] = []
    project_asset_ids = {a.id for a in project_assets}
    for aid, asset in share_assets_by_id.items():
        if aid in project_asset_ids:
            # Already grouped under project; still bump role if stronger.
            role_per_asset[aid] = stronger(role_per_asset.get(aid), share_role_by_asset[aid])
            continue
        if asset.project_id and asset.project_id in projects_by_id:
            grouped[asset.project_id].append(asset)
        else:
            standalone_assets.append(asset)
        role_per_asset[aid] = stronger(role_per_asset.get(aid), share_role_by_asset[aid])

    projects_payload: list[dict[str, Any]] = []
    for pid, assets in grouped.items():
        project = projects_by_id.get(pid)
        if project is None:
            continue
        projects_payload.append(
            {
                "project": {
                    "id": str(project.id),
                    "slug": project.slug,
                    "name": project.name,
                    "my_role": member_role_by_project.get(pid),
                },
                "assets": [
                    _asset_brief(
                        a,
                        owner=owners_by_id.get(a.owner_id),
                        my_role=role_per_asset[a.id],
                    )
                    for a in sorted(assets, key=lambda x: x.updated_at, reverse=True)
                ],
            }
        )
    projects_payload.sort(key=lambda p: p["project"]["name"])

    standalone_payload = [
        _asset_brief(
            a,
            owner=owners_by_id.get(a.owner_id),
            my_role=role_per_asset[a.id],
        )
        for a in sorted(standalone_assets, key=lambda x: x.updated_at, reverse=True)
    ]

    return {
        "projects": projects_payload,
        "standalone_assets": standalone_payload,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
