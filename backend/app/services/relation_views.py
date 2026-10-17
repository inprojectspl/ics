"""Read side of the relation graph (ADR-0016): the relation list of one asset
and the node projection shared with the neighbourhood. Edges whose other end
the viewer cannot see are dropped without reporting how many.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.domain_errors import NotFoundError
from app.models import Asset, AssetRelation, User
from app.services.asset_projection import load_metadata, metadata_fields
from app.services.graph_compact import (
    Shape,
    compact_edge,
    compact_node,
    drop_shadowed,
    edge_changed,
    other_end,
)
from app.services.read_size import estimated_tokens
from app.services.relations import INVERSE_LABEL, SYMMETRIC, graph_access_ids, visible_ids
from app.util import now as utc_now

Direction = Literal["both", "out", "in"]


_NODE_METADATA = ("doc_type", "freshness", "superseded_by", "summary")


async def project_nodes(
    session: AsyncSession, user: User, assets: Sequence[Asset]
) -> dict[UUID, dict[str, Any]]:
    """Node fields per asset, with freshness for this viewer: a successor
    counts only when the viewer can see it."""
    metadata = await load_metadata(session, assets, user)
    now = utc_now()
    out: dict[UUID, dict[str, Any]] = {}
    for a in assets:
        fields = metadata_fields(a, metadata.get(a.id), now, preview=True)
        out[a.id] = {
            "id": str(a.id),
            "slug": a.slug,
            "title": a.title,
            "kind": a.kind,
            **{key: fields[key] for key in _NODE_METADATA},
            "estimated_tokens": estimated_tokens(a),
        }
    return out


async def _visible_assets(
    session: AsyncSession, user: User, ids: Iterable[UUID]
) -> dict[UUID, Asset]:
    wanted = set(ids)
    if not wanted:
        return {}
    rows = await session.scalars(
        select(Asset).where(Asset.id.in_(wanted), permissions.visible_assets_filter(user))
    )
    return {a.id: a for a in rows}


def edge_fields(edge: AssetRelation, target_version_now: int | None) -> dict[str, Any]:
    changed = edge_changed(edge, target_version_now)
    return {
        "id": str(edge.id),
        "relation_type": edge.relation_type,
        "source_id": str(edge.source_asset_id),
        "target_id": str(edge.target_asset_id),
        "source_path": edge.source_path,
        "target_path": edge.target_path,
        "target_anchor": edge.target_anchor,
        "target_version": edge.target_version,
        "target_version_now": target_version_now,
        "target_changed": changed,
        "note": edge.note,
        "origin": edge.origin,
        "created_at": edge.created_at.isoformat() if edge.created_at else None,
    }


async def list_for_asset(
    session: AsyncSession,
    user: User,
    asset: Asset,
    *,
    types: Collection[str] | None = None,
    direction: Direction = "both",
    shape: Shape = "full",
) -> dict[str, Any]:
    """Outgoing edges grouped by type, incoming grouped by inverse label.
    Symmetric edges are listed once, as outgoing (as incoming when only
    incoming edges are asked for). `shape="compact"` gives the agent format
    (ADR-0016, section 10): outgoing edges first, then incoming."""
    outgoing_q = select(AssetRelation).where(AssetRelation.source_asset_id == asset.id)
    incoming_q = select(AssetRelation).where(AssetRelation.target_asset_id == asset.id)
    if types:
        outgoing_q = outgoing_q.where(AssetRelation.relation_type.in_(types))
        incoming_q = incoming_q.where(AssetRelation.relation_type.in_(types))
    # A symmetric edge has no direction, so it answers both "out" and "in".
    if direction == "out":
        incoming_q = incoming_q.where(AssetRelation.relation_type.in_(SYMMETRIC))
    elif direction == "in":
        outgoing_q = outgoing_q.where(AssetRelation.relation_type.in_(SYMMETRIC))
    edges = (
        await session.scalars(
            select(AssetRelation).from_statement(union_all(outgoing_q, incoming_q))
        )
    ).all()

    by_id = await _visible_assets(session, user, {other_end(e, asset.id) for e in edges})
    nodes = await project_nodes(session, user, list(by_id.values()))
    if shape == "compact":
        return _compact_list(
            asset, [e for e in edges if other_end(e, asset.id) in by_id], by_id, nodes
        )

    outgoing: dict[str, list[dict[str, Any]]] = {}
    incoming: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        other_id = other_end(e, asset.id)
        if other_id not in by_id:
            continue
        target = asset if e.target_asset_id == asset.id else by_id[other_id]
        item = {**edge_fields(e, target.version), "other": nodes[other_id]}
        if e.relation_type in SYMMETRIC:
            group, label = (incoming if direction == "in" else outgoing), e.relation_type
        elif e.source_asset_id == asset.id:
            group, label = outgoing, e.relation_type
        else:
            group, label = incoming, INVERSE_LABEL[e.relation_type]
        group.setdefault(label, []).append({**item, "label": label})
    return {"asset_id": str(asset.id), "outgoing": outgoing, "incoming": incoming}


def _compact_list(
    asset: Asset,
    edges: list[AssetRelation],
    by_id: dict[UUID, Asset],
    nodes: dict[UUID, dict[str, Any]],
) -> dict[str, Any]:
    slug_of = {asset.id: asset.slug} | {i: a.slug for i, a in by_id.items()}
    edges = sorted(drop_shadowed(edges), key=lambda e: e.source_asset_id != asset.id)
    table: dict[str, dict[str, Any]] = {}
    out: list[list[Any]] = []
    for e in edges:
        other_id = other_end(e, asset.id)
        target = asset if e.target_asset_id == asset.id else by_id[e.target_asset_id]
        out.append(compact_edge(e, slug_of, target.version, with_id=True))
        table.setdefault(slug_of[other_id], compact_node(nodes[other_id]))
    return {"asset": asset.slug, "nodes": table, "edges": out}


async def _visible_outgoing(
    session: AsyncSession, user: User, asset: Asset
) -> tuple[list[AssetRelation], dict[UUID, Asset]]:
    """Outgoing edges of `asset` in creation order whose target the viewer
    can see, and those targets."""
    edges = (
        await session.scalars(
            select(AssetRelation)
            .where(AssetRelation.source_asset_id == asset.id)
            .order_by(AssetRelation.created_at, AssetRelation.id)
        )
    ).all()
    targets = await _visible_assets(session, user, {e.target_asset_id for e in edges})
    return [e for e in edges if e.target_asset_id in targets], targets


async def outgoing_edges(session: AsyncSession, user: User, asset: Asset) -> list[dict[str, Any]]:
    """Outgoing edges of `asset` whose target the viewer can see, with the
    target's slug and anchor. The caller has checked graph access."""
    edges, targets = await _visible_outgoing(session, user, asset)
    return [
        {
            **edge_fields(e, targets[e.target_asset_id].version),
            "target_slug": targets[e.target_asset_id].slug,
        }
        for e in edges
    ]


async def outgoing_compact(session: AsyncSession, user: User, asset: Asset) -> dict[str, Any]:
    """`outgoing_edges` in the compact shape: `nodes` holds each target's
    title and decision fields (no summary), `edges` the triples."""
    edges, targets = await _visible_outgoing(session, user, asset)
    kept = drop_shadowed(edges)
    nodes = await project_nodes(session, user, list(targets.values()))
    slug_of = {asset.id: asset.slug} | {i: a.slug for i, a in targets.items()}
    table: dict[str, dict[str, Any]] = {}
    for e in kept:
        table.setdefault(
            slug_of[e.target_asset_id], compact_node(nodes[e.target_asset_id], summary=False)
        )
    return {
        "nodes": table,
        "edges": [compact_edge(e, slug_of, targets[e.target_asset_id].version) for e in kept],
    }


async def compact_relation(
    session: AsyncSession, user: User, edge: AssetRelation
) -> dict[str, Any]:
    """One edge in the compact shape (ADR-0016, section 10): `edge` is the
    triple with its `id`, `nodes` both ends without summaries. The caller
    has checked that `user` may see the edge."""
    order = (edge.source_asset_id, edge.target_asset_id)
    rows = await session.scalars(select(Asset).where(Asset.id.in_(order)))
    ends = {a.id: a for a in rows}
    nodes = await project_nodes(session, user, [ends[i] for i in order])
    slug_of = {i: a.slug for i, a in ends.items()}
    return {
        "edge": compact_edge(edge, slug_of, ends[edge.target_asset_id].version, with_id=True),
        "nodes": {slug_of[i]: compact_node(nodes[i], summary=False) for i in order},
    }


async def get_relation(session: AsyncSession, user: User, relation_id: UUID) -> dict[str, Any]:
    """`compact_relation` of one edge, when it shows in the relation list of
    one of its ends: graph access to that end and the other end visible.
    Anything else is `relation_not_found`, the same as a missing edge."""
    edge = await session.get(AssetRelation, relation_id)
    if edge is not None:
        ends = {edge.source_asset_id, edge.target_asset_id}
        if await visible_ids(session, user, ends) == ends and await graph_access_ids(
            session, user, ends
        ):
            return await compact_relation(session, user, edge)
    raise NotFoundError("relation_not_found", "relation not found")
