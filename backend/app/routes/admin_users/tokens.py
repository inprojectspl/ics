"""Admin: revoke every personal access token of a user (ADR-0020)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminUser
from app.db import get_session
from app.errors import ApiError
from app.models import User
from app.services import pat

from ._router import router


@router.post("/{user_id}/tokens/revoke")
async def revoke_user_tokens(
    user_id: UUID,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "user not found")
    count = await pat.revoke_all_for_user(
        session, user_id=user.id, actor=admin, reason="admin_revoke"
    )
    await session.commit()
    return {"revoked": count}
