"""Asset to AssetSummary serialization, shared by the personal vault list and
the project file list so both render with the same `AssetRow`. The route owns
the query that picks which assets to list.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.models import (
    Asset,
    AssetProjectShare,
    AssetShare,
    GitLabBinding,
    ProjectMember,
    ShareLink,
    User,
)
from app.services.asset_projection import load_metadata, metadata_fields
from app.util import now as utc_now


async def build_asset_summaries(
    session: AsyncSession,
    user: User,
    assets: Sequence[Asset],
    *,
    pin_at_by_asset: Mapping[UUID, datetime | None],
) -> list[dict]:
    """Serialize `assets` into AssetSummary rows from `user`'s perspective.

    `pin_at_by_asset` is supplied by the caller (it already needs the pin
    join to order the list); a missing key serializes as unpinned.
    """
    if not assets:
        return []

    asset_ids = [a.id for a in assets]

    # Direct per-user share role on each asset (if any).
    share_role_by_asset: dict[UUID, str] = {
        aid: role
        for aid, role in (
            await session.execute(
                select(AssetShare.asset_id, AssetShare.role).where(
                    AssetShare.asset_id.in_(asset_ids),
                    AssetShare.user_id == user.id,
                )
            )
        ).all()
    }

    # Caller's membership role on each asset's project.
    project_role_by_asset: dict[UUID, str] = {}
    project_ids = {a.project_id for a in assets if a.project_id}
    if project_ids:
        role_by_project = {
            pid: r
            for pid, r in (
                await session.execute(
                    select(ProjectMember.project_id, ProjectMember.role).where(
                        ProjectMember.project_id.in_(project_ids),
                        ProjectMember.user_id == user.id,
                        ProjectMember.accepted_at.is_not(None),
                    )
                )
            ).all()
        }
        for a in assets:
            if a.project_id and a.project_id in role_by_project:
                project_role_by_asset[a.id] = role_by_project[a.project_id]

    # Project shares (ADR-0017): the share role capped by the member's role.
    for aid, share_role, member_role in (
        await session.execute(
            select(AssetProjectShare.asset_id, AssetProjectShare.role, ProjectMember.role)
            .join(ProjectMember, ProjectMember.project_id == AssetProjectShare.project_id)
            .where(
                AssetProjectShare.asset_id.in_(asset_ids),
                ProjectMember.user_id == user.id,
                ProjectMember.accepted_at.is_not(None),
            )
        )
    ).all():
        capped = permissions.cap_project_share_role(share_role, member_role)
        project_role_by_asset[aid] = (
            permissions.pick_strongest_member_role(project_role_by_asset.get(aid), capped) or capped
        )

    # Owners of non-owned assets: hydrate display info in one round-trip.
    other_owner_ids = {a.owner_id for a in assets if a.owner_id != user.id}
    owners_by_id: dict[UUID, User] = {}
    if other_owner_ids:
        owners_by_id = {
            u.id: u
            for u in (
                await session.execute(select(User).where(User.id.in_(other_owner_ids)))
            ).scalars()
        }

    # Active ShareLink modes (sidebar filter counters + row chip).
    shares_by_asset: dict[str, set[str]] = {}
    for asset_id, mode in (
        await session.execute(
            select(ShareLink.asset_id, ShareLink.mode).where(
                ShareLink.asset_id.in_(asset_ids), ShareLink.revoked_at.is_(None)
            )
        )
    ).all():
        shares_by_asset.setdefault(str(asset_id), set()).add(mode)

    bound_ids = {
        str(row[0])
        for row in (
            await session.execute(
                select(GitLabBinding.asset_id).where(GitLabBinding.asset_id.in_(asset_ids))
            )
        ).all()
    }

    metadata = await load_metadata(session, assets, user)
    now = utc_now()

    def _strongest_role(a: Asset) -> str:
        if user.acts_as_admin or a.owner_id == user.id:
            return "owner"
        return (
            permissions.pick_strongest_member_role(
                share_role_by_asset.get(a.id),
                project_role_by_asset.get(a.id),
            )
            or "viewer"
        )

    def _access_source(a: Asset) -> str:
        if a.owner_id == user.id:
            return "owned"
        # Project-sourced wins for badge purposes when both apply, because
        # the project membership is the more durable relationship.
        if a.id in project_role_by_asset:
            return "project"
        return "direct"

    return [
        {
            "id": str(a.id),
            "slug": a.slug,
            "title": a.title,
            "kind": a.kind,
            "tags": list(a.tags or []),
            "size_bytes": a.size_bytes,
            "version": a.version,
            "security_status": a.security_status,
            "security_bypass": a.security_bypass,
            "active_share_modes": sorted(shares_by_asset.get(str(a.id), set())),
            "has_binding": str(a.id) in bound_ids,
            "pinned_at": (p.isoformat() if (p := pin_at_by_asset.get(a.id)) else None),
            "project_id": str(a.project_id) if a.project_id else None,
            "created_at": a.created_at.isoformat(),
            "updated_at": a.updated_at.isoformat(),
            "content_updated_at": (
                a.content_updated_at.isoformat() if a.content_updated_at else None
            ),
            "content_updated_by": str(a.content_updated_by) if a.content_updated_by else None,
            "my_role": _strongest_role(a),
            "access_source": _access_source(a),
            "owner": (
                None
                if a.owner_id == user.id
                else (
                    {
                        "id": str(a.owner_id),
                        "email": owners_by_id[a.owner_id].email,
                        "display_name": owners_by_id[a.owner_id].display_name,
                    }
                    if a.owner_id in owners_by_id
                    else None
                )
            ),
            **metadata_fields(a, metadata.get(a.id), now, preview=True),
        }
        for a in assets
    ]
