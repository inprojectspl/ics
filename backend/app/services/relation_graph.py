"""Neighbourhood of an asset in the relation graph (ADR-0016, section 6).
Breadth-first, one indexed UNION ALL per level rather than a recursive CTE,
which enumerates paths instead of nodes. A node is expanded only with graph
access, so a path through a hidden document does not exist.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain_errors import InvalidInputError
from app.models import Asset, AssetRelation, User
from app.services.graph_compact import (
    Shape,
    compact_edge,
    compact_node,
    drop_shadowed,
    other_end,
)
from app.services.relation_views import Direction, edge_fields, project_nodes
from app.services.relations import RELATION_TYPE_SET, SYMMETRIC, graph_access_ids, visible_ids

MAX_DEPTH = 3
MAX_NODES = 200
STRONG_TYPES: frozenset[str] = frozenset(
    {"derived_from", "depends_on", "supersedes", "part_of", "contradicts"}
)
# Lower wins when a level has more candidates than room left.
TYPE_WEIGHT: dict[str, int] = {
    t: i
    for i, t in enumerate(
        (
            "supersedes",
            "derived_from",
            "depends_on",
            "part_of",
            "contradicts",
            "references",
            "relates_to",
            "duplicates",
        )
    )
}


async def edges_touching(
    session: AsyncSession,
    ids: Iterable[UUID],
    types: Collection[str] | None = None,
    direction: Direction = "both",
) -> list[AssetRelation]:
    """Edges with either end in `ids`, optionally of `types` only. `out`
    keeps the edges leaving `ids`, `in` those arriving; a symmetric edge has
    no direction and answers both."""
    wanted = list(ids)
    by_source = select(AssetRelation).where(AssetRelation.source_asset_id.in_(wanted))
    by_target = select(AssetRelation).where(AssetRelation.target_asset_id.in_(wanted))
    if types is not None:
        by_source = by_source.where(AssetRelation.relation_type.in_(types))
        by_target = by_target.where(AssetRelation.relation_type.in_(types))
    if direction == "in":
        by_source = by_source.where(AssetRelation.relation_type.in_(SYMMETRIC))
    elif direction == "out":
        by_target = by_target.where(AssetRelation.relation_type.in_(SYMMETRIC))
    stmt = select(AssetRelation).from_statement(union_all(by_source, by_target))
    return list((await session.scalars(stmt)).unique().all())


async def neighbourhood(
    session: AsyncSession,
    actor: User,
    asset: Asset,
    *,
    depth: int = 1,
    types: Collection[str] | None = None,
    max_nodes: int = MAX_NODES,
    direction: Direction = "both",
    shape: Shape = "full",
) -> dict[str, Any]:
    """Nodes and edges around `asset`; the caller has checked graph access.
    Nearer nodes, then stronger types, win when `max_nodes` cuts the result.
    `skipped` counts, per type, the root's visible edges the type filter left
    out, so a reader of the default learns that other links exist."""
    depth = max(1, min(depth, MAX_DEPTH))
    max_nodes = max(1, min(max_nodes, MAX_NODES))
    wanted = set(types) if types else set(STRONG_TYPES)
    if not wanted <= RELATION_TYPE_SET:
        raise InvalidInputError("relation_type_invalid", "unknown relation type")

    depth_of: dict[UUID, int] = {asset.id: 0}
    expandable: set[UUID] = {asset.id}
    edges: dict[UUID, AssetRelation] = {}
    frontier: set[UUID] = {asset.id}
    truncated = False
    # The root's edges of every type come in one statement; the ones left
    # out only feed `skipped`.
    left_out: list[AssetRelation] = []
    seen_at_root: set[UUID] = set()
    for level in range(1, depth + 1):
        weight: dict[UUID, int] = {}
        rows = await edges_touching(session, frontier, None if level == 1 else wanted, direction)
        for e in rows:
            if e.relation_type not in wanted:
                left_out.append(e)
                continue
            edges[e.id] = e
            for end in (e.source_asset_id, e.target_asset_id):
                if end not in depth_of:
                    weight[end] = min(weight.get(end, 99), TYPE_WEIGHT[e.relation_type])
        others = {other_end(e, asset.id) for e in left_out} if level == 1 else set()
        seen = await visible_ids(session, actor, weight.keys() | others)
        if level == 1:
            seen_at_root = seen
        visible = sorted((n for n in seen if n in weight), key=lambda n: (weight[n], str(n)))
        room = max_nodes - len(depth_of)
        if len(visible) > room:
            truncated = True
            visible = visible[:room]
        for node in visible:
            depth_of[node] = level
        frontier = await graph_access_ids(session, actor, visible)
        expandable |= frontier
        if len(depth_of) >= max_nodes and frontier and level < depth:
            truncated = True
        if not frontier or len(depth_of) >= max_nodes:
            break

    skipped = dict(
        sorted(
            Counter(
                e.relation_type
                for e in left_out
                if (end := other_end(e, asset.id)) in seen_at_root and end not in depth_of
            ).items()
        )
    )
    assets = (await session.scalars(select(Asset).where(Asset.id.in_(depth_of)))).all()
    by_id = {a.id: a for a in assets}
    nodes = await project_nodes(session, actor, assets)
    ordered = sorted(assets, key=lambda a: (depth_of[a.id], a.title or "", str(a.id)))
    kept = [e for e in edges.values() if e.source_asset_id in by_id and e.target_asset_id in by_id]
    if shape == "compact":
        slug_of = {a.id: a.slug for a in assets}
        table: dict[str, dict[str, Any]] = {}
        for a in ordered:
            row = compact_node(nodes[a.id]) | {"depth": depth_of[a.id]}
            if a.id not in expandable:
                row["expandable"] = False
            table[a.slug] = row
        body: dict[str, Any] = {
            "root": asset.slug,
            "depth": depth,
            "types": sorted(wanted),
            "nodes": table,
            "edges": [
                compact_edge(e, slug_of, by_id[e.target_asset_id].version)
                for e in drop_shadowed(kept)
            ],
            "max_nodes": max_nodes,
        }
        if direction != "both":
            body["direction"] = direction
        if truncated:
            body["truncated"] = True
        if skipped:
            body["skipped"] = skipped
        return body
    return {
        "root_id": str(asset.id),
        "depth": depth,
        "types": sorted(wanted),
        "nodes": [
            {**nodes[a.id], "depth": depth_of[a.id], "expandable": a.id in expandable}
            for a in ordered
        ],
        "edges": [edge_fields(e, by_id[e.target_asset_id].version) for e in kept],
        "truncated": truncated,
        "skipped": skipped,
        "max_nodes": max_nodes,
    }
