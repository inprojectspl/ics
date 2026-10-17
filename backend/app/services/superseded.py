"""The successor a reader may be sent to from a superseded document (ADR-0015,
ADR-0016). It is offered only when this reader can open it (an ICS role, or a
usable share link whose gate admits them; never a password link), so the
banner never reveals a hidden document. The most recent edge wins.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.models import Asset, AssetRelation, User
from app.services import graph_signals, link_resolution


async def _candidates(session: AsyncSession, asset: Asset) -> list[tuple[Asset, datetime]]:
    rows = await session.execute(
        select(Asset, AssetRelation.created_at)
        .join(AssetRelation, AssetRelation.source_asset_id == Asset.id)
        .where(
            AssetRelation.target_asset_id == asset.id,
            AssetRelation.relation_type == "supersedes",
            Asset.deleted_at.is_(None),
        )
        .order_by(AssetRelation.created_at.desc(), AssetRelation.id)
    )
    return [(succ, since) for succ, since in rows.all()]


def _out(
    succ: Asset | graph_signals.Successor, since: datetime | None, href: str
) -> dict[str, Any]:
    return {
        "id": str(succ.id),
        "slug": succ.slug,
        "title": succ.title,
        "since": since.isoformat() if since else None,
        "href": href,
    }


async def for_viewer(session: AsyncSession, viewer: User, asset: Asset) -> dict[str, Any] | None:
    """Successor for a signed-in reader of `asset`: one statement over the
    successors they can see."""
    succ = (await graph_signals.latest_successors(session, viewer, [asset.id])).get(asset.id)
    if succ is None:
        return None
    return _out(succ, succ.since, f"/v/{succ.slug}")


async def for_share(
    session: AsyncSession,
    viewer: User | None,
    asset: Asset,
    allowed_domains: list[str],
) -> dict[str, Any] | None:
    """Successor for someone reading `asset` through a share link; `viewer`
    is their account when they are signed in."""
    for succ, since in await _candidates(session, asset):
        if viewer is not None and await permissions.effective_role(session, viewer, succ):
            return _out(succ, since, f"/v/{succ.slug}")
        for link in await link_resolution.load_shares(session, succ.id):
            if link_resolution.is_usable(link) and link_resolution.mode_admits(
                link, viewer, allowed_domains
            ):
                return _out(succ, since, f"/s/{link.token}")
    return None


async def from_href(session: AsyncSession, asset: Asset, href: str) -> dict[str, Any] | None:
    """Re-read a successor chosen earlier (the HTML viewer keeps only the
    href in its cookie). Returns None once the edge or the successor is
    gone, so a removed relation drops the banner at the next page load."""
    kind, _, key = href.strip("/").partition("/")
    for succ, since in await _candidates(session, asset):
        if kind == "v" and succ.slug == key:
            return _out(succ, since, href)
        if kind == "s":
            links = await link_resolution.load_shares(session, succ.id)
            if any(link.token == key and link_resolution.is_usable(link) for link in links):
                return _out(succ, since, href)
    return None
