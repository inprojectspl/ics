"""Project membership: invite, patch role, kick, leave, transfer-owner, accept."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, email_templates, tokens
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.email_outbox import queue_email
from app.errors import ApiError
from app.i18n import resolve_locale
from app.i18n.request import AcceptLanguage
from app.models import Project, ProjectMember, User
from app.services import sharing as sharing_svc

from ._models import AcceptInviteIn, InviteMemberIn, PatchMemberIn, TransferOwnerIn
from ._router import router
from ._shared import (
    _get_member,
    _get_project_by_slug,
    _member_row,
    _project_with_min_role,
    _utcnow,
)


@router.post("/{slug}/members", status_code=status.HTTP_201_CREATED)
async def invite_member(
    slug: str,
    body: InviteMemberIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    accept_language: AcceptLanguage = None,
) -> dict:
    project, _ = await _project_with_min_role(session, slug, user, "owner")
    invitee, is_new = await sharing_svc.resolve_or_create_invitee(session, body.email, settings)

    existing = await _get_member(session, project.id, invitee.id)
    if existing is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "already_member",
            "the user is already a member of this project",
        )

    member = ProjectMember(
        project_id=project.id,
        user_id=invitee.id,
        role=body.role,
        invited_by=user.id,
        accepted_at=None,
    )
    session.add(member)
    await session.flush()

    token = tokens.issue("project_invite", str(member.id))
    accept_url = f"{settings.base_url}/projects/{project.slug}/accept?t={token}"
    # A stub account has no password, so it cannot sign in to accept: give it
    # the same setup token the admin and per-document share invites send.
    # `next` brings the person back to the acceptance after the password is set.
    setup_url = (
        f"{settings.base_url}/setup?token={tokens.issue('invite', str(invitee.id))}"
        f"&next={quote(f'/projects/{project.slug}/accept?t={token}', safe='')}"
        if is_new
        else None
    )
    subj, txt, html = email_templates.project_invite(
        invited_by_email=user.email,
        project_name=project.name,
        role=body.role,
        accept_url=accept_url,
        setup_url=setup_url,
        locale=resolve_locale(invitee.locale, user.locale, accept_language=accept_language),
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
        action="project_member_invited",
        target=f"project:{project.id}",
        payload={
            "invited_email": invitee.email,
            "role": body.role,
            "new_account": is_new,
        },
    )
    await session.commit()
    await session.refresh(member)
    return _member_row(member, user=invitee)


@router.patch("/{slug}/members/{user_id}")
async def patch_member(
    slug: str,
    user_id: UUID,
    body: PatchMemberIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    project, _ = await _project_with_min_role(session, slug, user, "owner")
    member = await _get_member(session, project.id, user_id)
    if member is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "member_not_found", "member not found")
    if member.role == "owner":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "owner_role_locked",
            "the owner role changes only through transfer-owner",
        )
    old = member.role
    member.role = body.role
    target_user = await session.get(User, user_id)
    await audit.record(
        session,
        actor=user,
        action="project_member_role_changed",
        target=f"project:{project.id}",
        payload={"user_id": str(user_id), "from": old, "to": body.role},
    )
    await session.commit()
    await session.refresh(member)
    return _member_row(member, user=target_user)  # type: ignore[arg-type]


@router.delete("/{slug}/members/{user_id}", status_code=status.HTTP_200_OK)
async def kick_member(
    slug: str,
    user_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    project, _ = await _project_with_min_role(session, slug, user, "owner")
    member = await _get_member(session, project.id, user_id)
    if member is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "member_not_found", "member not found")
    if member.role == "owner":
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "cannot_kick_owner",
            "cannot remove the project owner (transfer ownership first)",
        )
    await audit.record(
        session,
        actor=user,
        action="project_member_kicked",
        target=f"project:{project.id}",
        payload={"user_id": str(user_id), "role": member.role},
    )
    await session.delete(member)
    await session.commit()
    return {"kicked": True}


@router.post("/{slug}/leave", status_code=status.HTTP_200_OK)
async def leave_project(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    project = await _get_project_by_slug(session, slug)
    member = await _get_member(session, project.id, user.id)
    if member is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "member_not_found", "member not found")
    if member.role == "owner":
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "owner_cannot_leave",
            "the project owner cannot leave the project; transfer ownership to another admin first",
        )
    await audit.record(
        session,
        actor=user,
        action="project_left",
        target=f"project:{project.id}",
        payload={"role": member.role},
    )
    await session.delete(member)
    await session.commit()
    return {"left": True}


@router.post("/{slug}/transfer-owner", status_code=status.HTTP_200_OK)
async def transfer_owner(
    slug: str,
    body: TransferOwnerIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Atomic ownership transfer. The partial unique owner index forbids two
    owners even momentarily, so the current owner is demoted before the
    target is promoted; a concurrent transfer loses on the index with 409.
    """
    project = await _get_project_by_slug(session, slug)
    # Caller must be current owner (or sys-admin).
    if not user.acts_as_admin:
        caller_member = await _get_member(session, project.id, user.id)
        if (
            caller_member is None
            or caller_member.accepted_at is None
            or caller_member.role != "owner"
        ):
            raise ApiError(
                status.HTTP_403_FORBIDDEN,
                "owner_required",
                "only the current project owner can transfer ownership",
            )

    target = await _get_member(session, project.id, body.user_id)
    if target is None or target.accepted_at is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "invalid_transfer_target",
            "the transfer target must be an accepted project member",
        )
    if target.role == "owner":
        return {"transferred": False, "reason": "target is already owner"}

    # Find current owner (may be the caller; for sys-admin the caller might
    # not be in members at all).
    current_owner = (
        await session.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project.id,
                ProjectMember.role == "owner",
            )
        )
    ).scalar_one_or_none()
    try:
        if current_owner is None:
            # Invariant broken (should never happen); recover by promoting target.
            target.role = "owner"
        else:
            current_owner.role = "editor"
            await session.flush()  # release partial unique index for the target promote
            target.role = "owner"
        await audit.record(
            session,
            actor=user,
            action="project_owner_transferred",
            target=f"project:{project.id}",
            payload={
                "from_user_id": str(current_owner.user_id) if current_owner else None,
                "to_user_id": str(target.user_id),
            },
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "ownership_conflict",
            "a concurrent ownership transfer won; reload and retry",
        ) from None
    return {"transferred": True}


@router.post("/accept-invite", status_code=status.HTTP_200_OK)
async def accept_invite(
    body: AcceptInviteIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    try:
        member_id_s = tokens.verify("project_invite", body.token)
    except tokens.TokenExpired:
        raise ApiError(
            status.HTTP_410_GONE, "invitation_expired", "the invitation link has expired"
        ) from None
    except tokens.TokenInvalid:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "token_invalid", "invalid token") from None

    try:
        member_id = UUID(member_id_s)
    except ValueError:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "token_invalid", "invalid token") from None

    member = await session.get(ProjectMember, member_id)
    if member is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "invitation_not_found", "invitation not found")
    if member.user_id != user.id:
        # Token issued to a different account: never honor it for the current user.
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "invitation_not_yours",
            "this invitation belongs to another account",
        )
    if member.accepted_at is not None:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "invitation_already_accepted",
            "the invitation has already been accepted",
        )

    member.accepted_at = _utcnow()
    project = await session.get(Project, member.project_id)
    await audit.record(
        session,
        actor=user,
        action="project_invite_accepted",
        target=f"project:{member.project_id}",
        payload={"role": member.role},
    )
    await session.commit()
    return {
        "accepted": True,
        "project_slug": project.slug if project else None,
        "project_name": project.name if project else None,
        "role": member.role,
    }
