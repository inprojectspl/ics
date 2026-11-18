"""Shared authorized, ranked and paginated browser document discovery."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.models import Asset, AssetPin, User
from app.services import asset_lifecycle
from app.services.asset_filters import (
    AssetScope,
    facet_counts,
    filter_predicates,
    fixed_filter_predicates,
    scope_predicates,
)
from app.services.asset_listing import build_asset_summaries
from app.services.asset_sort import AssetSortKey, SortOrder, asset_order_by
from app.services.document_search import SearchMatch, relevance_order, search_filter


async def discover_assets(
    session: AsyncSession,
    user: User,
    *,
    q: str | None = None,
    match: SearchMatch = "all",
    limit: int = 50,
    offset: int = 0,
    sort: AssetSortKey | None = None,
    order: SortOrder | None = None,
    scope: AssetScope = "all",
    filters: Sequence[str] = (),
    facets: bool = False,
) -> dict:
    trash = scope == "state:trash"
    base = [
        asset_lifecycle.trash_filter(user) if trash else permissions.visible_assets_filter(user)
    ]
    if q is not None:
        base.append(search_filter(q, match))
    # Sharing, source, freshness and the archive say nothing about a deleted
    # asset, so the trash neither filters nor counts by them.
    fixed = {} if trash else fixed_filter_predicates(user)
    groups = filter_predicates(filters, fixed)
    if not trash and "archive" not in groups:
        # The archive stays out until a filter asks for it (ADR-0029).
        groups["archive"] = asset_lifecycle.archive_predicate("active")
    scope_clause = true() if trash else scope_predicates(user)[scope]
    conditions = [*base, scope_clause, *groups.values()]
    if q is not None and sort is None:
        ordering = relevance_order(q, user, match)
    elif trash and sort is None:
        ordering = [Asset.deleted_at.desc(), Asset.id.desc()]
    else:
        ordering = asset_order_by(sort or "updated", order)
    # A window count keeps the rows and their total on the same DB snapshot.
    stmt = (
        select(Asset, AssetPin.pinned_at, func.count().over().label("total"))
        .outerjoin(AssetPin, AssetPin.for_user(user.id))
        .where(*conditions)
        .order_by(*ordering)
        .limit(limit)
        .offset(offset)
    )
    rows = (await session.execute(stmt)).all()
    total = int(rows[0].total) if rows else 0
    if not rows and offset:
        total = int(
            await session.scalar(select(func.count()).select_from(Asset).where(*conditions)) or 0
        )
    items = await build_asset_summaries(
        session,
        user,
        [a for a, _, _ in rows],
        pin_at_by_asset={a.id: pin for a, pin, _ in rows},
    )
    if trash:
        extra = await asset_lifecycle.trash_fields(session, [a for a, _, _ in rows])
        items = [{**item, **extra[a.id]} for item, (a, _, _) in zip(items, rows, strict=True)]
    result = {"items": items, "total": total}
    if facets:
        result.update(await facet_counts(session, user, base, scope, groups, fixed))
    return result
