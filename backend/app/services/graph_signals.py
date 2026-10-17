"""Signals the relation graph adds to asset projections (ADR-0015, ADR-0016):
`superseded` (only when the successor is visible, so the flag never confirms a
hidden document) and `basis_changed`. Each loader is one statement per page.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, case, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.models import Asset, AssetRelation, User

# Search score multiplier for a document superseded for the viewer: it still
# matches, but its successor (or any current hit) ranks above it.
SUPERSEDED_RANK_FACTOR = 0.5
# Bound on the `supersedes` steps followed to the newest document of a chain.
MAX_CHAIN_STEPS = 50


@dataclass(frozen=True)
class Successor:
    id: UUID
    slug: str
    title: str | None
    # When the `supersedes` edge was created.
    since: datetime | None


def _superseding_edges(viewer: User, *columns: Any) -> Select:
    """`supersedes` edges joined with their successor (`Asset`), limited to
    successors `viewer` can see."""
    return (
        select(*columns)
        .select_from(AssetRelation)
        .join(Asset, Asset.id == AssetRelation.source_asset_id)
        .where(
            AssetRelation.relation_type == "supersedes",
            permissions.visible_assets_filter(viewer),
        )
    )


def _changed_basis_edges(viewer: User, *columns: Any) -> Select:
    """`derived_from` edges whose target (`Asset`) is visible to `viewer` and
    has moved past the version recorded on the edge."""
    return (
        select(*columns)
        .select_from(AssetRelation)
        .join(Asset, Asset.id == AssetRelation.target_asset_id)
        .where(
            AssetRelation.relation_type == "derived_from",
            AssetRelation.target_version.is_not(None),
            Asset.version > AssetRelation.target_version,
            permissions.visible_assets_filter(viewer),
        )
    )


# `Asset` and `AssetRelation` never correlate to the outer query of the EXISTS
# builders below, so the id may be a column of an alias or a CTE.
_OWN_TABLES = (Asset, AssetRelation)


def visible_successor_exists(viewer: User, target_id: Any) -> ColumnElement[bool]:
    """EXISTS: the document `target_id` is superseded for `viewer`.

    The visible successors are an uncorrelated `IN` subquery with a FROM of
    its own, so `target_id` may be `Asset.id` of the outer query itself (the
    list filters), not only a column of an alias or a CTE."""
    visible = select(Asset.id).where(permissions.visible_assets_filter(viewer)).correlate(None)
    return (
        select(AssetRelation.id)
        .where(
            AssetRelation.relation_type == "supersedes",
            AssetRelation.target_asset_id == target_id,
            AssetRelation.source_asset_id.in_(visible),
        )
        .correlate_except(AssetRelation)
        .exists()
    )


def changed_basis_exists(viewer: User, source_id: Any) -> ColumnElement[bool]:
    """EXISTS: a visible basis of the document `source_id` has changed."""
    return (
        _changed_basis_edges(viewer, AssetRelation.id)
        .where(AssetRelation.source_asset_id == source_id)
        .correlate_except(*_OWN_TABLES)
        .exists()
    )


async def latest_successors(
    session: AsyncSession, viewer: User, ids: Iterable[UUID]
) -> dict[UUID, Successor]:
    """The visible successor per superseded asset in `ids`. With several
    successors the most recent edge wins."""
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await session.execute(
        _superseding_edges(
            viewer,
            AssetRelation.target_asset_id,
            Asset.id,
            Asset.slug,
            Asset.title,
            AssetRelation.created_at,
        )
        .where(AssetRelation.target_asset_id.in_(wanted))
        .order_by(AssetRelation.created_at.desc(), AssetRelation.id)
    )
    out: dict[UUID, Successor] = {}
    for target_id, succ_id, slug, title, since in rows.all():
        out.setdefault(target_id, Successor(succ_id, slug, title, since))
    return out


async def chain_ends(
    session: AsyncSession, viewer: User, direct: dict[UUID, Successor]
) -> dict[UUID, Successor]:
    """The newest document of each `supersedes` chain, per superseded asset,
    given its direct successors. A hidden document ends the chain, and so
    does a cycle (possible through documents an edge author could not see)."""
    ends = dict(direct)
    seen = {start: {start, succ.id} for start, succ in direct.items()}
    active = set(direct)
    for _ in range(MAX_CHAIN_STEPS):
        if not active:
            break
        nxt = await latest_successors(session, viewer, {ends[start].id for start in active})
        moved = set()
        for start in active:
            succ = nxt.get(ends[start].id)
            if succ is None or succ.id in seen[start]:
                continue
            seen[start].add(succ.id)
            ends[start] = succ
            moved.add(start)
        active = moved
    return ends


async def changed_bases(session: AsyncSession, viewer: User, ids: Iterable[UUID]) -> set[UUID]:
    """Assets in `ids` with a `derived_from` edge whose visible target has a
    newer version than the one recorded on the edge."""
    wanted = set(ids)
    if not wanted:
        return set()
    rows = await session.execute(
        _changed_basis_edges(viewer, AssetRelation.source_asset_id)
        .where(AssetRelation.source_asset_id.in_(wanted))
        .distinct()
    )
    return set(rows.scalars())


def rank_factor(viewer: User, asset_id: ColumnElement[UUID]) -> ColumnElement[float]:
    """SQL multiplier for a search score: `SUPERSEDED_RANK_FACTOR` when the
    asset is superseded for `viewer`, 1 otherwise."""
    superseded = visible_successor_exists(viewer, asset_id)
    return case((superseded, literal(SUPERSEDED_RANK_FACTOR)), else_=literal(1.0))
