"""Per-user storage quota and a per-user cap on html bundle size.

Usage is a live `SUM(size_bytes)`, cheap per owner; a stored counter would drift
under concurrent upload and delete.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_errors import LimitExceededError
from app.models import Asset


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
