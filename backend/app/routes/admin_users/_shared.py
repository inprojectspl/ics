"""Shared helpers: user row serializer + asset-stats bulk query."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, User
from app.util import now as utc_now


def _user_row(u: User, *, asset_count: int = 0, asset_bytes: int = 0) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "display_name": u.display_name,
        "role": u.role,
        "auth_method": u.auth_method,
        "email_verified": u.email_verified_at is not None,
        "email_verified_at": (u.email_verified_at.isoformat() if u.email_verified_at else None),
        "locked_until": u.locked_until.isoformat() if u.locked_until else None,
        "locked": u.locked_until is not None and u.locked_until > utc_now(),
        "storage_quota_bytes": u.storage_quota_bytes,
        "bundle_max_bytes": u.bundle_max_bytes,
        "html_autobypass": u.html_autobypass,
        "asset_count": asset_count,
        "asset_bytes": asset_bytes,
        "created_at": u.created_at.isoformat(),
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


async def _asset_stats(
    session: AsyncSession,
    owner_ids: list,
) -> dict[str, tuple[int, int]]:
    """Per-owner asset count and size sum for the given owners, in one query."""
    if not owner_ids:
        return {}
    stmt = (
        select(
            Asset.owner_id,
            func.count(Asset.id),
            func.coalesce(func.sum(Asset.size_bytes), 0),
        )
        .where(Asset.deleted_at.is_(None))
        .where(Asset.owner_id.in_(owner_ids))
        .group_by(Asset.owner_id)
    )
    rows = (await session.execute(stmt)).all()
    return {str(owner_id): (int(cnt), int(bytes_)) for owner_id, cnt, bytes_ in rows}
