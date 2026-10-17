"""Link hierarchy (ADR-0005): which URL represents an asset, and where to
send a visitor on `/v/<slug>` who cannot open it as-is. Free of FastAPI types
so routes and the notification dispatcher share one set of rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import domain_of
from app.config import Settings
from app.constants import ShareMode
from app.models import Asset, ShareLink, User
from app.permissions import EffectiveRole
from app.services.sharing import build_asset_url, build_share_url
from app.util import now as utc_now

# `password` and `magic_email` are absent: the URL alone does not grant access.
CANONICAL_PRIORITY: tuple[ShareMode, ...] = ("org_sso", "public")

EntryAction = Literal["view", "redirect", "login"]

#: Why a link is dead. `None` means it is alive.
LifecycleFault = Literal["revoked", "expired", "spent"]


@dataclass(frozen=True)
class EntryDecision:
    """`view`: render `/v/<slug>` as-is; `redirect`: send to `/s/<token>`;
    `login`: authenticate first, then re-run the resolver. "No way in" is
    the absence of a decision (`None`), which the caller answers with 404
    so a slug never confirms that an asset exists."""

    action: EntryAction
    token: str | None = None


def link_lifecycle(share: ShareLink, at: datetime | None = None) -> LifecycleFault | None:
    """The one definition of "this link is dead", independent of who asks.

    `_resolve_share` maps the fault onto its own 410 messages and the
    resolver just filters on `None`, so a new lifecycle gate cannot land
    in one of them and be missed by the other.
    """
    at = at or utc_now()
    if share.revoked_at is not None:
        return "revoked"
    if share.expires_at is not None and share.expires_at <= at:
        return "expired"
    if share.max_views is not None and (share.view_count or 0) >= share.max_views:
        return "spent"
    return None


def is_usable(share: ShareLink, at: datetime | None = None) -> bool:
    return link_lifecycle(share, at) is None


def mode_admits(share: ShareLink, user: User | None, allowed_domains: list[str]) -> bool:
    """Does this identity satisfy the link's own gate? Shared with the share
    endpoints so the resolver never advertises a link they would refuse.
    `password` is never admitted here (the HTTP layer runs the challenge); for
    `magic_email` a logged-in account already proves the mailbox.
    """
    if share.mode == "public":
        return True
    if user is None:
        return False
    if share.mode == "org_sso":
        return domain_of(user.email) in allowed_domains
    if share.mode == "magic_email":
        allowed = {e.lower() for e in (share.allowed_emails or [])}
        return user.email.lower() in allowed
    return False


def _canonical_sort_key(share: ShareLink) -> tuple[int, int, datetime]:
    return (
        CANONICAL_PRIORITY.index(share.mode),
        # A link with an expiry date still works today, but it is a worse
        # permanent address than one without, so prefer the durable one.
        0 if share.expires_at is None else 1,
        share.created_at,
    )


def _advertisable(shares: list[ShareLink], mode: ShareMode) -> list[ShareLink]:
    """Usable links of `mode`, oldest first. A link with `max_views` is never
    advertised: sending anyone else to it would spend its recipient's budget.
    """
    return sorted(
        (s for s in shares if s.mode == mode and s.max_views is None and is_usable(s)),
        key=lambda s: s.created_at,
    )


def pick_canonical(shares: list[ShareLink]) -> ShareLink | None:
    """The asset's address, or None when nothing qualifies (then the
    address stays `/v/<slug>`)."""
    candidates = [s for m in CANONICAL_PRIORITY for s in _advertisable(shares, m)]
    if not candidates:
        return None
    return min(candidates, key=_canonical_sort_key)


def _candidate(
    shares: list[ShareLink],
    mode: ShareMode,
    user: User | None,
    allowed_domains: list[str],
) -> ShareLink | None:
    """First link of `mode` that admits this visitor.

    Per-link, not per-mode: two `magic_email` links on one asset name
    different recipients, so testing only the oldest one would answer
    "no way in" to someone who holds the newer one.
    """
    for share in _advertisable(shares, mode):
        # `password` is not decided by identity: the challenge is on the
        # share page, so offering the link is the answer.
        if share.mode == "password" or mode_admits(share, user, allowed_domains):
            return share
    return None


def resolve_entry(
    *,
    role: EffectiveRole | None,
    user: User | None,
    shares: list[ShareLink],
    allowed_domains: list[str],
) -> EntryDecision | None:
    """Where a visitor on `/v/<slug>` should end up. Ordered by how little the
    visitor has to do, except that `org_sso` beats `public` because it
    identifies the user in the audit log.
    """
    if role is not None:
        return EntryDecision("view")

    for mode in ("org_sso", "public", "password", "magic_email"):
        link = _candidate(shares, mode, user, allowed_domains)
        if link is not None:
            return EntryDecision("redirect", link.token)

    # Anonymous, and the only way in is an org link: logging in may well
    # produce a role or a matching domain, so the resolver runs again
    # after authentication rather than declaring a dead end now.
    if user is None and _advertisable(shares, "org_sso"):
        return EntryDecision("login")

    return None


async def load_shares(session: AsyncSession, asset_id: UUID) -> list[ShareLink]:
    """Every share link of an asset; the resolver weighs all four modes, so it
    cannot pre-filter."""
    rows = await session.execute(select(ShareLink).where(ShareLink.asset_id == asset_id))
    return list(rows.scalars())


async def pick_canonical_share(session: AsyncSession, asset_id: UUID) -> ShareLink | None:
    """`pick_canonical` with losing rows filtered in SQL: this runs on `/doc`,
    the hottest read endpoint."""
    rows = await session.execute(
        select(ShareLink).where(
            ShareLink.asset_id == asset_id,
            ShareLink.mode.in_(CANONICAL_PRIORITY),
            ShareLink.revoked_at.is_(None),
            ShareLink.max_views.is_(None),
            ShareLink.expires_at.is_(None) | (ShareLink.expires_at > utc_now()),
        )
    )
    return pick_canonical(list(rows.scalars()))


async def canonical_url(session: AsyncSession, settings: Settings, asset: Asset) -> str:
    """The address to show for `asset`. Falls back to `/v/<slug>`, which
    is always correct for whoever can already see the document."""
    share = await pick_canonical_share(session, asset.id)
    if share is None:
        return build_asset_url(settings, asset.slug)
    return build_share_url(settings, share.token)
