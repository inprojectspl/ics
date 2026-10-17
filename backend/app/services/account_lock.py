"""Tells an administrator's lock apart from a failed-attempt lockout.

Both set `users.locked_until`; only the audit trail records who locked the
account, so the latest lock event decides.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User
from app.util import now as utc_now

_LOCK_EVENTS = ("account_locked", "user_locked_by_admin", "user_unlocked_by_admin")


async def locked_by_admin(session: AsyncSession, user: User) -> bool:
    """True while an active lock on `user` was set by an administrator."""
    if user.locked_until is None or user.locked_until <= utc_now():
        return False
    last = await session.scalar(
        select(AuditLog.action)
        .where(AuditLog.target == f"user:{user.id}", AuditLog.action.in_(_LOCK_EVENTS))
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    return last == "user_locked_by_admin"
