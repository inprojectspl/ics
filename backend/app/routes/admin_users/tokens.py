"""Admin: revoke every token of a user: personal access tokens (ADR-0020)
and the OAuth sign-ins of MCP clients."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminUser
from app.db import get_session
from app.errors import ApiError
from app.models import User

from ._router import router
from ._shared import revoke_all_tokens


@router.post("/{user_id}/tokens/revoke")
async def revoke_user_tokens(
    user_id: UUID,
    admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "user not found")
    pats, grants = await revoke_all_tokens(session, user, admin=admin, reason="admin_revoke")
    await session.commit()
    return {"revoked": pats + grants}
