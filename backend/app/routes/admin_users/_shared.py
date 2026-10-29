"""Shared helpers: user row serializer, asset-stats bulk query, token revoke."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Asset, User
from app.oauth import tokens as oauth_tokens
from app.services import pat


async def revoke_all_tokens(
    session: AsyncSession, user: User, *, admin: User, reason: str
) -> tuple[int, int]:
    """Revoke the user's personal access tokens and sign their OAuth clients
    out (ADR-0020); returns both counts."""
    pats = await pat.revoke_all_for_user(session, user_id=user.id, actor=admin, reason=reason)
    grants = await oauth_tokens.revoke_user_grants(
        session, user.id, reason=reason, access_ttl=get_settings().oauth_access_token_ttl
    )
    return pats, grants


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
        "locked": u.is_locked,
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
