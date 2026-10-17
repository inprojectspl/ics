"""List users (paginated, filtered, with summary) + per-user details."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import AdminUser
from app.db import get_session
from app.errors import ApiError
from app.models import User
from app.util import now as utc_now

from ._router import router
from ._shared import _asset_stats, _user_row


@router.get("")
async def list_users(
    _admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    role: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 25,
) -> dict:
    """Paginated user list + summary counters.

    Returns `{summary, users, total, page, page_size}`. Summary is computed
    over the *full* table (not the filtered/paged view) so the header chips
    always show global state.
    """
    now = utc_now()
    cutoff30 = now - timedelta(days=30)

    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if q:
        needle = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(User.email).like(needle),
                func.lower(func.coalesce(User.display_name, "")).like(needle),
            )
        )
    if status_filter == "locked":
        stmt = stmt.where(User.locked_until.is_not(None), User.locked_until > now)
    elif status_filter == "unverified":
        stmt = stmt.where(User.email_verified_at.is_(None))
    elif status_filter == "active30d":
        stmt = stmt.where(User.last_login_at.is_not(None), User.last_login_at > cutoff30)
    elif status_filter == "password":
        stmt = stmt.where(User.auth_method == "password")
    elif status_filter == "google_sso":
        stmt = stmt.where(User.auth_method == "google_sso")

    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    users = (
        (
            await session.execute(
                stmt.order_by(User.created_at.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        )
        .scalars()
        .all()
    )

    # Summary in one query with `COUNT(...) FILTER (WHERE ...)` instead of
    # 5 separate full scans of `users`: with 10k users that is 1 plan
    # instead of 5. Requires PG >= 9.4.
    summary_row = (
        await session.execute(
            select(
                func.count().label("total"),
                func.count()
                .filter(User.last_login_at.is_not(None), User.last_login_at > cutoff30)
                .label("active_30d"),
                func.count()
                .filter(User.locked_until.is_not(None), User.locked_until > now)
                .label("locked"),
                func.count().filter(User.email_verified_at.is_(None)).label("unverified"),
                func.count().filter(User.role == "admin").label("admins"),
            )
        )
    ).one()
    summary = {
        "total": int(summary_row.total),
        "active_30d": int(summary_row.active_30d),
        "locked": int(summary_row.locked),
        "unverified": int(summary_row.unverified),
        "admins": int(summary_row.admins),
    }

    # Scoped to the visible page so the planner uses `ix_assets_owner_id`.
    visible_user_ids = [u.id for u in users]
    stats = await _asset_stats(session, visible_user_ids)
    return {
        "summary": summary,
        "users": [
            _user_row(
                u,
                asset_count=stats.get(str(u.id), (0, 0))[0],
                asset_bytes=stats.get(str(u.id), (0, 0))[1],
            )
            for u in users
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{user_id}")
async def get_user(
    user_id: UUID,
    _admin: AdminUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "user_not_found", "user not found")
    stats = await _asset_stats(session, [user.id])
    cnt, bytes_ = stats.get(str(user.id), (0, 0))
    return _user_row(user, asset_count=cnt, asset_bytes=bytes_)
