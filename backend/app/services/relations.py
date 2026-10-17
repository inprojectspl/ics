"""Typed relations between assets (ADR-0016). An end the actor may not see is
reported exactly like a missing asset (`asset_not_found`), so the graph never
confirms that a hidden document exists. `origin` only records provenance.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal, get_args
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions
from app.config import get_settings
from app.domain_errors import ConflictError, InvalidInputError, LimitExceededError, NotFoundError
from app.models import Asset, AssetRelation, User
from app.services import relation_anchor

RelationType = Literal[
    "derived_from",
    "supersedes",
    "depends_on",
    "part_of",
    "references",
    "relates_to",
    "duplicates",
    "contradicts",
]
Origin = Literal["manual", "agent", "extracted", "integration"]
RELATION_TYPE_SET: frozenset[str] = frozenset(get_args(RelationType))
SYMMETRIC: frozenset[str] = frozenset({"relates_to", "contradicts"})
# Types that must not form a cycle in the subgraph the actor can see.
ACYCLIC: frozenset[str] = frozenset({"supersedes", "part_of"})
INVERSE_LABEL: dict[str, str] = {
    "derived_from": "basis_for",
    "supersedes": "superseded_by",
    "depends_on": "required_by",
    "part_of": "has_part",
    "references": "referenced_by",
    "relates_to": "relates_to",
    "duplicates": "duplicated_by",
    "contradicts": "contradicts",
}
MAX_EDGES_PER_ASSET = 200
# Origins that take over an extracted edge when added again explicitly.
_EXPLICIT: frozenset[str] = frozenset({"manual", "agent", "integration"})


def origin_for_transport(transport: str | None) -> Origin:
    """Bearer calls come from agents (MCP); anything else is a person."""
    return "agent" if audit.is_agent_transport(transport) else "manual"


def _asset_not_found() -> NotFoundError:
    return NotFoundError("asset_not_found", "asset not found")


def _relation_not_found() -> NotFoundError:
    return NotFoundError("relation_not_found", "relation not found")


async def ids_matching(
    session: AsyncSession, ids: Iterable[UUID], allowed: ColumnElement[bool]
) -> set[UUID]:
    """The subset of `ids` whose asset row matches `allowed`."""
    wanted = set(ids)
    if not wanted:
        return set()
    rows = await session.scalars(select(Asset.id).where(Asset.id.in_(wanted), allowed))
    return set(rows)


async def visible_ids(session: AsyncSession, user: User, ids: Iterable[UUID]) -> set[UUID]:
    """The subset of `ids` the user can read (any content role, not deleted)."""
    return await ids_matching(session, ids, permissions.visible_assets_filter(user))


async def graph_access_ids(session: AsyncSession, user: User, ids: Iterable[UUID]) -> set[UUID]:
    """The subset of `ids` whose relations the user may read."""
    return await ids_matching(session, ids, permissions.graph_accessible_assets_filter(user))


async def _load_target(
    session: AsyncSession, user: User, target_id: UUID | None, target_slug: str | None
) -> Asset:
    if target_id is None and not target_slug:
        raise _asset_not_found()
    target, _ = await permissions.get_asset_with_role(
        session,
        user=user,
        min_role="viewer",
        asset_id=target_id,
        slug=None if target_id is not None else target_slug,
    )
    return target


async def edge_counts(session: AsyncSession, ids: Iterable[UUID]) -> dict[UUID, int]:
    """Edges touching each asset in `ids` (either end), in one statement."""
    wanted = list(set(ids))
    if not wanted:
        return {}
    end = union_all(
        select(AssetRelation.source_asset_id.label("asset_id")).where(
            AssetRelation.source_asset_id.in_(wanted)
        ),
        select(AssetRelation.target_asset_id.label("asset_id")).where(
            AssetRelation.target_asset_id.in_(wanted)
        ),
    ).subquery()
    rows = await session.execute(select(end.c.asset_id, func.count()).group_by(end.c.asset_id))
    counts = dict.fromkeys(wanted, 0)
    counts.update({asset_id: int(n) for asset_id, n in rows.all()})
    return counts


async def edge_count(session: AsyncSession, asset_id: UUID) -> int:
    return (await edge_counts(session, [asset_id]))[asset_id]


async def _creates_visible_cycle(
    session: AsyncSession, user: User, source_id: UUID, target_id: UUID, relation_type: str
) -> bool:
    """Would `source -> target` close a cycle of `relation_type`? Walks forward
    from the target through documents the actor can see only, so a refusal
    never reveals a path through a hidden document."""
    seen, frontier = {target_id}, {target_id}
    while frontier:
        rows = await session.execute(
            select(AssetRelation.target_asset_id).where(
                AssetRelation.source_asset_id.in_(frontier),
                AssetRelation.relation_type == relation_type,
            )
        )
        nxt = set(rows.scalars()) - seen
        nxt = await visible_ids(session, user, nxt)
        if source_id in nxt:
            return True
        seen |= nxt
        frontier = nxt
    return False


async def _audit(
    session: AsyncSession,
    actor: User,
    action: Literal["relation_added", "relation_updated", "relation_removed"],
    edge: AssetRelation,
    *,
    transport: str | None,
    client_id_external: str | None,
    **extra: object,
) -> None:
    await audit.record(
        session,
        actor=actor,
        action=action,
        target=f"relation:{edge.id}",
        payload={
            "source": str(edge.source_asset_id),
            "target": str(edge.target_asset_id),
            "type": edge.relation_type,
            "origin": edge.origin,
            **extra,
        },
        transport=transport,
        client_id_external=client_id_external,
    )


async def add_relation(
    session: AsyncSession,
    *,
    actor: User,
    source_id: UUID,
    relation_type: str,
    target_id: UUID | None = None,
    target_slug: str | None = None,
    source_path: str | None = None,
    target_path: str | None = None,
    target_anchor: str | None = None,
    note: str | None = None,
    origin: Origin | None = None,
    transport: str | None = None,
    client_id_external: str | None = None,
) -> AssetRelation:
    """Create an edge (or take over an extracted one). Needs editor on the
    source and a visible target. Does not commit."""
    if relation_type not in RELATION_TYPE_SET:
        raise InvalidInputError("relation_type_invalid", "unknown relation type")
    source, _ = await permissions.get_asset_with_role(
        session, user=actor, min_role="editor", asset_id=source_id
    )
    target = await _load_target(session, actor, target_id, target_slug)
    if source.id == target.id:
        raise InvalidInputError("relation_self", "an asset cannot relate to itself")
    target_anchor = await relation_anchor.check_target_location(
        target, target_path, target_anchor, get_settings()
    )
    origin = origin or origin_for_transport(transport)

    src, dst = source.id, target.id
    if relation_type in SYMMETRIC and dst < src:
        # One row per unordered pair; the anchor belongs to one side only.
        if target_anchor:
            raise InvalidInputError(
                "relation_anchor_invalid", "a symmetric relation cannot point at a heading"
            )
        src, dst = dst, src
        source_path, target_path = target_path, source_path

    existing = await session.scalar(
        select(AssetRelation).where(
            AssetRelation.source_asset_id == src,
            AssetRelation.target_asset_id == dst,
            AssetRelation.relation_type == relation_type,
            func.coalesce(AssetRelation.source_path, "") == (source_path or ""),
            func.coalesce(AssetRelation.target_path, "") == (target_path or ""),
            func.coalesce(AssetRelation.target_anchor, "") == (target_anchor or ""),
        )
    )
    if existing is not None:
        if existing.origin == "extracted" and origin in _EXPLICIT:
            # An explicit origin means extraction stops owning (and removing) this edge.
            existing.origin = origin
            if note is not None:
                existing.note = note
            await _audit(
                session,
                actor,
                "relation_updated",
                existing,
                transport=transport,
                client_id_external=client_id_external,
                previous_origin="extracted",
            )
            return existing
        raise ConflictError("relation_exists", "this relation already exists")

    if max((await edge_counts(session, (src, dst))).values()) >= MAX_EDGES_PER_ASSET:
        raise LimitExceededError("relation_limit", "too many relations on this asset")
    if relation_type in ACYCLIC and await _creates_visible_cycle(
        session, actor, src, dst, relation_type
    ):
        raise ConflictError("relation_cycle", "this relation would create a cycle")

    edge = AssetRelation(
        source_asset_id=src,
        target_asset_id=dst,
        relation_type=relation_type,
        source_path=source_path,
        target_path=target_path,
        target_anchor=target_anchor,
        target_version=(target if dst == target.id else source).version,
        note=note,
        origin=origin,
        created_by=actor.id,
    )
    session.add(edge)
    await session.flush()
    await _audit(
        session,
        actor,
        "relation_added",
        edge,
        transport=transport,
        client_id_external=client_id_external,
    )
    return edge


async def _editable_edge(session: AsyncSession, actor: User, relation_id: UUID) -> AssetRelation:
    """The edge, if the actor sees both ends and is an editor of one of them.
    Anything else is `relation_not_found`, the same as a missing edge."""
    edge = await session.get(AssetRelation, relation_id)
    if edge is None:
        raise _relation_not_found()
    roles = []
    for asset_id in (edge.source_asset_id, edge.target_asset_id):
        role = await permissions.visible_role(session, actor, await session.get(Asset, asset_id))
        if role is None:
            raise _relation_not_found()
        roles.append(role)
    if all(permissions.is_read_only(r) for r in roles):
        raise _relation_not_found()
    return edge


async def update_relation(
    session: AsyncSession,
    *,
    actor: User,
    relation_id: UUID,
    note: str | None = None,
    set_note: bool = False,
    refresh_target_version: bool = False,
    transport: str | None = None,
    client_id_external: str | None = None,
) -> AssetRelation:
    """Change the note (`set_note=True`, `note=None` clears it) and/or record
    the target's current version, which clears `basis_changed`."""
    edge = await _editable_edge(session, actor, relation_id)
    changed: list[str] = []
    if set_note and note != edge.note:
        edge.note = note
        changed.append("note")
    if refresh_target_version:
        target = await session.get(Asset, edge.target_asset_id)
        if target is not None and edge.target_version != target.version:
            edge.target_version = target.version
            changed.append("target_version")
    if changed:
        await _audit(
            session,
            actor,
            "relation_updated",
            edge,
            transport=transport,
            client_id_external=client_id_external,
            fields=changed,
        )
    return edge


async def remove_relation(
    session: AsyncSession,
    *,
    actor: User,
    relation_id: UUID,
    transport: str | None = None,
    client_id_external: str | None = None,
) -> None:
    edge = await _editable_edge(session, actor, relation_id)
    await _audit(
        session,
        actor,
        "relation_removed",
        edge,
        transport=transport,
        client_id_external=client_id_external,
    )
    await session.delete(edge)
    await session.flush()
