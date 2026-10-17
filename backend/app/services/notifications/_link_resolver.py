"""Asset to share link lookup for notifications. No usable link gives None and
the dispatcher skips the card: without a link there is nothing to click.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.constants import ShareMode
from app.services.link_resolution import pick_canonical_share
from app.services.sharing import build_share_url

from ._types import AssetLink, AssetLinkVisibility

_VISIBILITY: Final[dict[ShareMode, AssetLinkVisibility]] = {
    "org_sso": AssetLinkVisibility.ORG,
    "public": AssetLinkVisibility.PUBLIC,
}


async def resolve_asset_share_link(
    session: AsyncSession,
    asset_id: UUID,
    settings: Settings,
) -> AssetLink | None:
    """The same link ICS shows in the address bar: the canonical choice has
    one definition (`link_resolution.pick_canonical`), so a notification
    never advertises a different link than the UI for the same asset."""
    share = await pick_canonical_share(session, asset_id)
    if share is None:
        return None
    return AssetLink(
        url=build_share_url(settings, share.token),
        visibility=_VISIBILITY[share.mode],
    )
