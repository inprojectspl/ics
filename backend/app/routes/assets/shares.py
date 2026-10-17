"""Per-user shares (AssetShare) + project assignment.

The share operations require a role that may share externally
(`permissions.can_share_externally`). Listing/create/delete act on
asset_shares; project assignment has its own endpoint.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, email_templates, permissions, tokens
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.email_outbox import queue_email
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import AssetShare, User
from app.services import project_shares as project_shares_svc
from app.services import sharing as sharing_svc
from app.services.notifications import events as notification_events

router = APIRouter(prefix="/api/assets", tags=["assets"])


class PatchAssetProjectIn(BaseModel):
    project_id: UUID | None


class CreateAssetShareIn(BaseModel):
    email: EmailStr
    role: Literal["editor", "viewer"]


@router.patch("/by-slug/{slug}/project")
async def patch_asset_project(
    slug: str,
    body: PatchAssetProjectIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Move an asset into or out of a project. Owner-only; the target
    project also requires the caller to be its owner or editor."""
    asset = await permissions.get_asset_by_slug_or_404(session, slug)
    role = await permissions.effective_role(session, user, asset)
    if role not in ("owner_file", "project_owner"):
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")

    target_project_id = body.project_id
    if target_project_id is not None:
        await permissions.assert_project_contributor(session, user, target_project_id)

    old = asset.project_id
    asset.project_id = target_project_id
    await project_shares_svc.drop_for_new_home(session, asset)
    await audit.record(
        session,
        actor=user,
        action="asset_project_changed",
        target=f"asset:{asset.id}",
        payload={
            "from": str(old) if old else None,
            "to": str(target_project_id) if target_project_id else None,
        },
    )
    await session.commit()
    if target_project_id is not None and target_project_id != old:
        await notification_events.emit_added(asset, target_project_id, user)
    return {"project_id": str(target_project_id) if target_project_id else None}


@router.get("/by-slug/{slug}/shares")
async def list_asset_shares(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    asset = await permissions.get_asset_by_slug_or_404(session, slug)
    role = await permissions.effective_role(session, user, asset)
    if not permissions.can_share_externally(role):
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    rows = (
        await session.execute(
            select(AssetShare, User)
            .join(User, User.id == AssetShare.user_id)
            .where(AssetShare.asset_id == asset.id)
            .order_by(AssetShare.granted_at.asc())
        )
    ).all()
    return [
        {
            "id": str(s.id),
            "user_id": str(s.user_id),
            "email": u.email,
            "display_name": u.display_name,
            "role": s.role,
            "granted_at": s.granted_at.isoformat(),
            "granted_by": str(s.granted_by) if s.granted_by else None,
        }
        for s, u in rows
    ]


@router.post("/by-slug/{slug}/shares", status_code=status.HTTP_201_CREATED)
async def create_asset_share(
    slug: str,
    body: CreateAssetShareIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> dict:
    asset = await permissions.get_asset_by_slug_or_404(session, slug)
    role = await permissions.effective_role(session, user, asset)
    if not permissions.can_share_externally(role):
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")

    invitee, is_new = await sharing_svc.resolve_or_create_invitee(session, body.email, settings)

    if invitee.id == asset.owner_id:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "share_with_owner",
            "cannot share a file with its owner",
        )

    existing = (
        await session.execute(
            select(AssetShare).where(
                AssetShare.asset_id == asset.id,
                AssetShare.user_id == invitee.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "share_exists",
            "this user already has access to this file",
        )

    share = AssetShare(
        asset_id=asset.id,
        user_id=invitee.id,
        role=body.role,
        granted_by=user.id,
    )
    session.add(share)
    await session.flush()

    # If we just created a fresh account, send them a regular invite so
    # they can set a password; without that they can't log in to see
    # the file at all.
    if is_new:
        token = tokens.issue("invite", str(invitee.id))
        link = f"{settings.base_url}/setup?token={token}"
        subj, txt, html = email_templates.invite(
            invited_by_email=user.email,
            setup_url=link,
            locale=resolve_locale(user.locale, accept_language=accept_language),
        )
        await queue_email(
            session,
            to_email=invitee.email,
            subject=subj,
            body=txt,
            body_html=html,
            purpose="invite",
        )

    await audit.record(
        session,
        actor=user,
        action="asset_share_granted",
        target=f"asset:{asset.id}",
        payload={"to_user": str(invitee.id), "role": body.role, "new_account": is_new},
    )
    await session.commit()
    await session.refresh(share)
    return {
        "id": str(share.id),
        "user_id": str(invitee.id),
        "email": invitee.email,
        "display_name": invitee.display_name,
        "role": share.role,
        "granted_at": share.granted_at.isoformat(),
        "new_account": is_new,
    }


@router.delete(
    "/by-slug/{slug}/shares/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_asset_share(
    slug: str,
    user_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    asset = await permissions.get_asset_by_slug_or_404(session, slug)
    role = await permissions.effective_role(session, user, asset)
    if not permissions.can_share_externally(role):
        raise ApiError(status.HTTP_404_NOT_FOUND, "asset_not_found", "asset not found")
    try:
        await sharing_svc.revoke_asset_share(
            session,
            asset_id=asset.id,
            target_user_id=user_id,
            actor=user,
        )
    except sharing_svc.ShareNotFoundError as e:
        raise ApiError(status.HTTP_404_NOT_FOUND, "share_not_found", "share not found") from e
    await session.commit()
