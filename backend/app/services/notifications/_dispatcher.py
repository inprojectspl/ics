"""Dispatcher: orchestrates provider lookup, link resolution and sending.

Called from `routes/bindings.sync` after the commit. All "should we send at
all" logic is here; the route checks no conditions and only delegates.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.constants import SecurityStatus
from app.i18n import Locale, resolve_locale
from app.models import Asset, GitLabBinding, User

from ._link_resolver import resolve_asset_share_link
from ._registry import get_provider
from ._types import NotificationContext, UnknownProviderError

logger = logging.getLogger("ics.notifications.dispatcher")


async def dispatch_sync_notification(
    *,
    binding: GitLabBinding,
    asset: Asset,
    new_version: int,
    file_count: int,
    commit_sha: str,
    security_status: SecurityStatus | None,
    session: AsyncSession,
    settings: Settings,
) -> None:
    """Sends nothing when the binding has notifications disabled, its provider
    is unknown, or the asset has no org/public share link to click."""
    if not binding.webhook_url or not binding.provider:
        return
    try:
        provider = get_provider(binding.provider)
    except UnknownProviderError:
        logger.warning(
            "binding %s: unknown provider %r, skipping the notification",
            binding.id,
            binding.provider,
        )
        return

    link = await resolve_asset_share_link(session, asset.id, settings)
    if link is None:
        logger.info(
            "binding %s: asset %s has no share link, skipping the notification",
            binding.id,
            asset.id,
        )
        return

    ctx = NotificationContext(
        asset_title=asset.title or asset.slug,
        asset_slug=asset.slug,
        version=new_version,
        commit_sha=commit_sha,
        file_count=file_count,
        security_status=security_status,
        link=link,
        locale=await _card_locale(session, binding, asset),
    )
    await provider.send(binding.webhook_url, ctx)


async def _card_locale(session: AsyncSession, binding: GitLabBinding, asset: Asset) -> Locale:
    """The sync request comes from CI, not from a browser, so the card
    follows the binding author's stored locale, then the asset owner's."""
    ids = [i for i in (binding.created_by, asset.owner_id) if i is not None]
    rows = await session.execute(select(User.id, User.locale).where(User.id.in_(ids)))
    locales = dict(rows.tuples().all())
    return resolve_locale(*(locales.get(i) for i in ids))
