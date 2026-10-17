"""User state changes: patch role/quota/bundle-limit/name, lock/unlock, delete."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import AdminUser
from app.constants import ROLES
from app.db import get_session
from app.errors import ApiError
from app.models import Asset, User
from app.services import pat
from app.util import now as utc_now

from ._models import LockIn, PatchUserIn
from ._router import router
from ._shared import _asset_stats, _user_row


@router.patch("/{user_id}")
async def patch_user(
    user_id: UUID,
    body: PatchUserIn,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "user not found")

    audited = []
    if body.display_name is not None and body.display_name != user.display_name:
        old = user.display_name
        user.display_name = body.display_name
        await audit.record(
            session,
            actor=admin,
            action="user_display_name_changed",
            target=f"user:{user.id}",
            payload={"from": old, "to": body.display_name},
        )
        audited.append("display_name")

    if body.role is not None and body.role != user.role:
        if body.role not in ROLES:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, "invalid_role", f"invalid role: {body.role}"
            )
        # Guardrail: don't let an admin demote the last remaining admin,
        # otherwise the org locks itself out of admin functionality.
        if user.role == "admin" and body.role != "admin":
            count_admins = (
                await session.execute(select(func.count(User.id)).where(User.role == "admin"))
            ).scalar_one()
            if count_admins <= 1:
                raise ApiError(
                    status.HTTP_400_BAD_REQUEST,
                    "last_admin",
                    "cannot remove the admin role from the last administrator",
                )
        old = user.role
        user.role = body.role
        await audit.record(
            session,
            actor=admin,
            action="user_role_changed",
            target=f"user:{user.id}",
            payload={"from": old, "to": body.role},
        )
        audited.append("role")

    if (
        body.storage_quota_bytes is not None
        and body.storage_quota_bytes != user.storage_quota_bytes
    ):
        old_quota = user.storage_quota_bytes
        user.storage_quota_bytes = body.storage_quota_bytes
        await audit.record(
            session,
            actor=admin,
            action="user_quota_changed",
            target=f"user:{user.id}",
            payload={"from_bytes": old_quota, "to_bytes": body.storage_quota_bytes},
        )
        audited.append("storage_quota_bytes")

    if body.bundle_max_bytes is not None and body.bundle_max_bytes != user.bundle_max_bytes:
        old_limit = user.bundle_max_bytes
        user.bundle_max_bytes = body.bundle_max_bytes
        await audit.record(
            session,
            actor=admin,
            action="user_bundle_limit_changed",
            target=f"user:{user.id}",
            payload={"from_bytes": old_limit, "to_bytes": body.bundle_max_bytes},
        )
        audited.append("bundle_max_bytes")

    if body.html_autobypass is not None and body.html_autobypass != user.html_autobypass:
        old_autobypass = user.html_autobypass
        user.html_autobypass = body.html_autobypass
        await audit.record(
            session,
            actor=admin,
            action="user_autobypass_changed",
            target=f"user:{user.id}",
            payload={"from": old_autobypass, "to": body.html_autobypass},
        )
        audited.append("html_autobypass")

    if audited:
        await session.commit()
        await session.refresh(user)

    stats = await _asset_stats(session, [user.id])
    cnt, bytes_ = stats.get(str(user.id), (0, 0))
    return _user_row(user, asset_count=cnt, asset_bytes=bytes_)


@router.post("/{user_id}/lock", status_code=status.HTTP_200_OK)
async def lock_user(
    user_id: UUID,
    body: LockIn,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "user not found")
    if user.id == admin.id:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "cannot_lock_self", "you cannot lock yourself")
    until = utc_now() + timedelta(minutes=body.minutes)
    user.locked_until = until
    # A lock must also cut off the tokens a local client may still hold (ADR-0020).
    await pat.revoke_all_for_user(session, user_id=user.id, actor=admin, reason="account_locked")
    await audit.record(
        session,
        actor=admin,
        action="user_locked_by_admin",
        target=f"user:{user.id}",
        payload={"until": until.isoformat(), "minutes": body.minutes, "reason": body.reason},
    )
    await session.commit()
    return {"locked_until": until.isoformat()}


@router.delete("/{user_id}/lock", status_code=status.HTTP_200_OK)
async def unlock_user(
    user_id: UUID,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "user not found")
    user.locked_until = None
    await audit.record(
        session,
        actor=admin,
        action="user_unlocked_by_admin",
        target=f"user:{user.id}",
    )
    await session.commit()
    return {"locked_until": None}


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
async def delete_user(
    user_id: UUID,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Hard delete, cascading to the user's assets, shares and bindings;
    audit entries stay (actor is a string). Returns the cascaded asset count."""
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "user not found")
    if user.id == admin.id:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "cannot_delete_self", "you cannot delete yourself"
        )
    if user.role == "admin":
        count_admins = (
            await session.execute(select(func.count(User.id)).where(User.role == "admin"))
        ).scalar_one()
        if count_admins <= 1:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "last_admin",
                "cannot delete the last administrator",
            )

    cascade_assets = (
        await session.execute(select(func.count(Asset.id)).where(Asset.owner_id == user.id))
    ).scalar_one()

    await audit.record(
        session,
        actor=admin,
        action="user_deleted_by_admin",
        target=f"user:{user.id}",
        payload={
            "deleted_email": user.email,
            "deleted_role": user.role,
            "cascade_assets": int(cascade_assets),
        },
    )
    await session.delete(user)
    await session.commit()
    return {"deleted": True, "cascade_assets": int(cascade_assets)}
