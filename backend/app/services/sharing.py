"""Lifecycle operations on shares (ShareLink + AssetShare) and ICS URL builders.
Raises plain business exceptions, never HTTP errors; the caller maps them.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit
from app.auth import domain_of
from app.config import Settings
from app.models import AssetShare, ShareLink, User
from app.util import now as utc_now


def build_app_url(settings: Settings, path: str) -> str:
    """Absolute URL of an app-relative path (`/account/...`, `/v/...`)."""
    return f"{settings.base_url.rstrip('/')}{path}"


def build_asset_url(settings: Settings, slug: str) -> str:
    """Canonical URL of the internal view (`/v/<slug>`): the address for
    anyone with a role on the asset. Sibling of `build_share_url`, so building
    ICS addresses does not scatter across call sites."""
    return build_app_url(settings, f"/v/{slug}")


def build_share_url(settings: Settings, token: str, *, magic: str | None = None) -> str:
    """Canonical ShareLink URL. The `magic` parameter is for magic-email
    links (one-shot token in the query string)."""
    base = build_app_url(settings, f"/s/{token}")
    return f"{base}?m={magic}" if magic else base


class ShareNotFoundError(LookupError):
    """The ShareLink or AssetShare does not exist (or the user has no access).
    HTTP mapper: 404."""


async def revoke_share_link(session: AsyncSession, *, share_id: UUID, actor: User) -> None:
    """Idempotent revoke: a no-op if already revoked (no audit-log spam).
    Does not check permissions here; the caller must first make sure the
    actor has rights to this asset (e.g. via
    `permissions.get_shareable_asset`)."""
    share = await session.get(ShareLink, share_id)
    if share is None:
        raise ShareNotFoundError(str(share_id))
    if share.revoked_at is None:
        share.revoked_at = utc_now()
        await audit.record(
            session,
            actor=actor,
            action="share_revoked",
            target=f"share:{share.id}",
        )


async def revoke_asset_share(
    session: AsyncSession,
    *,
    asset_id: UUID,
    target_user_id: UUID,
    actor: User,
) -> None:
    """Delete an AssetShare entry (per-user grant). See the permissions note
    in `revoke_share_link`."""
    share = (
        await session.execute(
            select(AssetShare).where(
                AssetShare.asset_id == asset_id,
                AssetShare.user_id == target_user_id,
            )
        )
    ).scalar_one_or_none()
    if share is None:
        raise ShareNotFoundError(f"asset_share:{asset_id}:{target_user_id}")
    await audit.record(
        session,
        actor=actor,
        action="asset_share_revoked",
        target=f"asset:{asset_id}",
        payload={"user_id": str(target_user_id), "role": share.role},
    )
    await session.delete(share)


async def resolve_or_create_invitee(
    session: AsyncSession, email: str, settings: Settings
) -> tuple[User, bool]:
    """Find user by email; create stub `auth_method='invite'` if missing.
    Returns (user, is_new_account)."""
    email = email.lower().strip()
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        return existing, False

    # New account: same role-downgrade rule as /api/auth/invite.
    role = "user" if domain_of(email) in settings.allowed_domain_list else "external"
    new_user = User(
        email=email,
        display_name=email.split("@")[0],
        role=role,
        auth_method="invite",
        email_verified_at=None,
    )
    session.add(new_user)
    await session.flush()
    return new_user, True
