"""Per-user storage quota and a per-user cap on html bundle size.

Usage is a live `SUM(size_bytes)`, cheap per owner; a stored counter would drift
under concurrent upload and delete.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import MICRO_APPLICATION
from app.domain_errors import LimitExceededError
from app.models import Asset, MicroAppEnvironment, MicroAppStats, User


class QuotaExceededError(LimitExceededError):
    """The user's storage quota or per-bundle cap would be exceeded."""


async def used_bytes(session: AsyncSession, user_id: UUID) -> int:
    """Sum of size_bytes across the user's non-deleted assets."""
    result = await session.execute(
        select(func.coalesce(func.sum(Asset.size_bytes), 0)).where(
            Asset.owner_id == user_id, Asset.deleted_at.is_(None)
        )
    )
    return int(result.scalar_one() or 0)


async def assert_can_grow(
    session: AsyncSession,
    user_id: UUID,
    *,
    incoming_bytes: int,
    quota_bytes: int,
) -> int:
    """Raise QuotaExceededError if adding `incoming_bytes` would push the user over quota.
    Returns current usage so callers can include it in error context."""
    used = await used_bytes(session, user_id)
    if used + incoming_bytes > quota_bytes:
        raise QuotaExceededError(
            "storage_quota_exceeded",
            f"storage quota exceeded: using {used} B of {quota_bytes} B "
            f"(short by {used + incoming_bytes - quota_bytes} B)",
        )
    return used


def assert_bundle_fits(*, total_bytes: int, bundle_max_bytes: int) -> None:
    """Raise QuotaExceededError when one html bundle exceeds the per-user cap.
    Every bundle write path must call it, or a lowered limit has a back door."""
    if total_bytes > bundle_max_bytes:
        raise QuotaExceededError(
            "bundle_too_large",
            f"bundle too large: {total_bytes} B, limit {bundle_max_bytes} B",
        )


# Owners whose micro-applications are over their data limit. Written by
# the measuring worker every 30 s, read on every app request (one SISMEMBER
# instead of an aggregate); it expires when measurements stop, so a dead
# worker never blocks writes for good.
FULL_OWNERS_KEY = "microapp:data_full_owners"
FULL_OWNERS_TTL_S = 300


async def refresh_full_owners(session: AsyncSession) -> set[str]:
    """Recompute which owners are at or over `microapp_data_max_bytes` from
    the last measurement and publish the set."""
    from app.redis_client import get_redis

    used = func.coalesce(func.sum(MicroAppStats.db_bytes), 0)
    rows = await session.scalars(
        select(Asset.owner_id)
        .join(User, User.id == Asset.owner_id)
        .join(MicroAppEnvironment, MicroAppEnvironment.asset_id == Asset.id)
        .join(MicroAppStats, MicroAppStats.environment_id == MicroAppEnvironment.id)
        .where(Asset.kind == MICRO_APPLICATION, Asset.deleted_at.is_(None))
        .group_by(Asset.owner_id, User.microapp_data_max_bytes)
        .having(used >= User.microapp_data_max_bytes)
    )
    full = {str(owner_id) for owner_id in rows}
    redis = get_redis()
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(FULL_OWNERS_KEY)
        if full:
            pipe.sadd(FULL_OWNERS_KEY, *full)
            pipe.expire(FULL_OWNERS_KEY, FULL_OWNERS_TTL_S)
        await pipe.execute()
    return full


async def owner_data_full(owner_id: UUID) -> bool:
    from app.redis_client import get_redis

    try:
        member = get_redis().sismember(FULL_OWNERS_KEY, str(owner_id))
        return bool(await cast(Awaitable[int], member))
    except Exception:
        # Redis down: the soft limit is not enforced rather than every app
        # refusing writes.
        return False
