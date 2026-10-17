"""Assigning an asset to additional projects (ADR-0017).

Reading and changing the list needs a role that may share the asset
(file owner or owner of the home project); adding a project also needs
owner or editor membership there (`services.project_shares.set_share`).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.db import get_session
from app.domain_errors import AccessDeniedError
from app.models import Asset, User
from app.routes.assets.shares import router
from app.services import project_shares as project_shares_svc
from app.services.notifications import events as notification_events
from app.services.project_shares import ProjectShareRole


async def _shareable(session: AsyncSession, asset_id: UUID, user: User) -> Asset:
    """404 for anyone who cannot see the asset (`get_shareable_asset` answers
    403 there), 403 for a collaborator who may not share it."""
    asset, role = await permissions.get_viewable_asset_by_id(session, asset_id, user)
    if not permissions.can_share_externally(role):
        raise AccessDeniedError("share_forbidden", "you cannot share this asset")
    return asset


class PutProjectShareIn(BaseModel):
    project_id: UUID
    role: ProjectShareRole


@router.get("/{asset_id}/project-shares")
async def list_project_shares(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    asset = await _shareable(session, asset_id, user)
    return await project_shares_svc.list_shares(session, asset)


@router.put("/{asset_id}/project-shares")
async def put_project_share(
    asset_id: UUID,
    body: PutProjectShareIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    asset = await _shareable(session, asset_id, user)
    created = await project_shares_svc.set_share(
        session, asset=asset, project_id=body.project_id, role=body.role, actor=user
    )
    await session.commit()
    if created:
        await notification_events.emit_added(asset, body.project_id, user)
    return await project_shares_svc.list_shares(session, asset)


@router.delete("/{asset_id}/project-shares/{project_id}")
async def delete_project_share(
    asset_id: UUID,
    project_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    asset = await _shareable(session, asset_id, user)
    await project_shares_svc.remove_share(session, asset=asset, project_id=project_id, actor=user)
    await session.commit()
    return await project_shares_svc.list_shares(session, asset)
