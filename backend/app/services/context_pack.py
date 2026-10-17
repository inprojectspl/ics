"""Agent context pack (ADR-0019): the documents of one task in one call.

Only documents the caller has graph access to take part, and nothing reports
how many were left out except `hidden_count` for owners of the mapped project.
Ordering, the budget and the response shape are in `context_pack_output`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, distinct, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.domain_errors import NotFoundError
from app.models import (
    Asset,
    AssetExternalRef,
    Project,
    ProjectKeyDocument,
    User,
)
from app.services import graph_signals, project_links
from app.services.external_refs import validate_key
from app.services.project_shares import in_project_filter
from app.services.relation_graph import STRONG_TYPES, edges_touching
from app.services.relations import INVERSE_LABEL

System = Literal["openproject", "project_standard"]
MAX_DEPTH = 2
DEFAULT_BUDGET = 1800
MAX_BUDGET = 4000
# Key documents fill in only for a task with less context than this.
KEY_DOCUMENTS_BELOW = 3
MAX_NEIGHBOURS = 60
WEAK_TYPES: frozenset[str] = frozenset({"references", "relates_to", "duplicates"})
# A contradiction is cheap to list and costly to miss, so it ranks with depends_on.
_NEIGHBOUR_WEIGHT = {"depends_on": 0, "contradicts": 0, "derived_from": 1}

# Ordering groups (ADR-0019, "Ordering"): a document linked to the task itself
# always comes before graph neighbours.
(
    G_REQUIRED,
    G_DIRECT,
    G_INHERITED,
    G_KEY,
    G_DIRECT_REFERENCE,
    G_NEIGHBOUR,
    G_REFERENCE,
    G_DELIVERABLE,
) = range(8)


@dataclass(frozen=True)
class ContextRequest:
    system: System = "openproject"
    wp: str = ""
    ancestors: tuple[str, ...] = ()
    project: str | None = None
    scope: str | None = None
    depth: int = 1
    budget_tokens: int = DEFAULT_BUDGET
    include: frozenset[str] = frozenset()

    def keys(self) -> list[tuple[str, str]]:
        """`(system, entity)` of the task and each ancestor, nearest first. A
        Project Standard task may name OP work packages among its ancestors
        (a local node inside a mirrored project, ADR-0018)."""
        out = []
        for value in (self.wp, *self.ancestors):
            if self.system == "project_standard" and value.startswith("n-"):
                out.append(("project_standard", "node"))
            else:
                out.append(("openproject", "work_package"))
        return out

    def validate(self) -> None:
        for (system, entity), value in zip(self.keys(), (self.wp, *self.ancestors), strict=True):
            validate_key(system, entity, value, self.scope if entity == "node" else None)


@dataclass
class Slot:
    """One document on its way into the pack, at its best position so far."""

    asset: Asset
    rank: tuple[int, int, int]
    via: list[dict[str, Any]] = field(default_factory=list)
    required: bool = False
    # Set on a superseded document whose successor took its place.
    collapsed_into: UUID | None = None


@dataclass
class Collected:
    slots: dict[UUID, Slot]
    seeds: list[UUID]
    project: Project | None
    project_role: str | None
    external: str | None
    unmapped: bool
    # No visible document is linked to the task or its ancestors.
    unlinked: bool
    pinned_moved: set[UUID]
    hidden_count: int | None


def _add(
    slots: dict[UUID, Slot],
    asset: Asset,
    rank: tuple[int, int, int],
    via: dict[str, Any],
    *,
    required: bool = False,
) -> Slot:
    slot = slots.get(asset.id)
    if slot is None:
        slot = slots[asset.id] = Slot(asset=asset, rank=rank)
    slot.rank = min(slot.rank, rank)
    slot.via.append(via)
    slot.required = slot.required or required
    return slot


def _task_filter(req: ContextRequest) -> Any:
    """Match on `ix_asset_external_refs_lookup` (system, entity, external_id)."""
    values = (req.wp, *req.ancestors)
    by_kind: dict[tuple[str, str], list[str]] = {}
    for key, value in zip(req.keys(), values, strict=True):
        by_kind.setdefault(key, []).append(value)
    clauses = []
    for (system, entity), ids in by_kind.items():
        clause = and_(
            AssetExternalRef.system == system,
            AssetExternalRef.entity == entity,
            AssetExternalRef.external_id.in_(ids),
        )
        if entity == "node":
            clause = and_(clause, AssetExternalRef.external_scope == req.scope)
        clauses.append(clause)
    return or_(*clauses)


async def _resolve_project(
    session: AsyncSession, user: User, req: ContextRequest
) -> tuple[Project | None, str | None]:
    """The mapped ICS project (by external id, then by ICS slug) and the
    caller's role there. No mapping and no membership look the same."""
    if not req.project:
        return None, None
    try:
        return await project_links.project_by_external(
            session, actor=user, system=req.system, external_id=req.project
        )
    except NotFoundError:
        pass
    project = await session.scalar(
        select(Project).where(Project.slug == req.project, Project.deleted_at.is_(None))
    )
    if project is None:
        return None, None
    role = await permissions.project_role(session, user, project)
    return (project, role) if role else (None, None)


async def _linked(
    session: AsyncSession, user: User, req: ContextRequest, slots: dict[UUID, Slot]
) -> tuple[int, set[UUID], bool]:
    """Add the task's linked documents; return the context count, the
    documents whose pinned version moved on and whether any is linked."""
    values = [req.wp, *req.ancestors]
    rows = (
        await session.execute(
            select(AssetExternalRef, Asset)
            .join(Asset, Asset.id == AssetExternalRef.asset_id)
            .where(
                _task_filter(req),
                # Graph access implies read access, so no visibility filter.
                permissions.graph_accessible_assets_filter(user),
            )
            .order_by(AssetExternalRef.created_at, AssetExternalRef.id)
        )
    ).all()
    context: set[UUID] = set()
    pinned_moved: set[UUID] = set()
    for ref, asset in rows:
        level = values.index(ref.external_id) if ref.external_id in values else len(values)
        via: dict[str, Any] = {"kind": "direct"} if level == 0 else {"kind": "inherited"}
        if level:
            via["wp"] = ref.external_id
        via |= {"role": ref.role, "required": ref.required}
        # Why the document is linked often matters more than the role.
        via |= {key: value for key in ("label", "note") if (value := getattr(ref, key))}
        if ref.pinned_version is not None and asset.version > ref.pinned_version:
            pinned_moved.add(asset.id)
        if ref.role == "deliverable":
            if "deliverables" in req.include:
                _add(slots, asset, (G_DELIVERABLE, level, 0), via)
            continue
        if ref.role == "context":
            context.add(asset.id)
        if ref.required:
            _add(slots, asset, (G_REQUIRED, level, 0), via, required=True)
        elif ref.role == "context":
            _add(slots, asset, (G_DIRECT if level == 0 else G_INHERITED, level, 0), via)
        else:
            group = G_DIRECT_REFERENCE if level == 0 else G_REFERENCE
            _add(slots, asset, (group, level, 0), via)
    return len(context), pinned_moved, bool(rows)


async def _key_documents(
    session: AsyncSession, user: User, project: Project, slots: dict[UUID, Slot]
) -> None:
    rows = (
        await session.execute(
            select(ProjectKeyDocument, Asset)
            .join(Asset, Asset.id == ProjectKeyDocument.asset_id)
            .where(
                ProjectKeyDocument.project_id == project.id,
                permissions.graph_accessible_assets_filter(user),
            )
            .order_by(ProjectKeyDocument.position)
        )
    ).all()
    for key, asset in rows:
        via = {"kind": "project_key", "reason": key.reason}
        _add(slots, asset, (G_KEY, key.position, 0), via)


async def _promote_successors(session: AsyncSession, user: User, slots: dict[UUID, Slot]) -> None:
    """A superseded document gives its place and `required` flag to its
    visible successor (ADR-0019), following chains; the successor must be
    graph accessible to enter the pack."""
    pending = [s for s in slots.values() if s.collapsed_into is None]
    for _ in range(4):
        succ = await graph_signals.latest_successors(session, user, [s.asset.id for s in pending])
        if not succ:
            return
        ids = {v.id for v in succ.values()}
        accessible = {
            a.id: a
            for a in await session.scalars(
                select(Asset).where(
                    Asset.id.in_(ids), permissions.graph_accessible_assets_filter(user)
                )
            )
        }
        promoted = []
        for old in pending:
            info = succ.get(old.asset.id)
            new = accessible.get(info.id) if info else None
            if new is None or new.id == old.asset.id:
                continue
            old.collapsed_into = new.id
            via = {"kind": "successor_of", "slug": old.asset.slug, "required": old.required}
            promoted.append(_add(slots, new, old.rank, via, required=old.required))
        pending = [s for s in promoted if s.collapsed_into is None]
        if not pending:
            return


async def _neighbours(
    session: AsyncSession, user: User, req: ContextRequest, slots: dict[UUID, Slot]
) -> list[UUID]:
    """Graph neighbours of the linked documents, breadth first, one statement
    per level; a neighbour must be graph accessible and only such nodes are
    expanded. Returns the seeds."""
    seeds = [i for i, s in slots.items() if s.collapsed_into is None and s.rank[0] <= G_KEY]
    if req.depth < 1 or not seeds:
        return seeds
    types = set(STRONG_TYPES) | (WEAK_TYPES if "references" in req.include else set())
    frontier, added = set(seeds), 0
    for level in range(1, req.depth + 1):
        best: dict[UUID, tuple[int, UUID, str]] = {}
        for e in await edges_touching(session, frontier, types):
            for here, other, label in (
                (e.source_asset_id, e.target_asset_id, e.relation_type),
                (e.target_asset_id, e.source_asset_id, INVERSE_LABEL[e.relation_type]),
            ):
                if here not in frontier or other in slots:
                    continue
                weight = _NEIGHBOUR_WEIGHT.get(e.relation_type, 2)
                if other not in best or weight < best[other][0]:
                    best[other] = (weight, here, label)
        if not best:
            break
        assets = (
            await session.scalars(
                select(Asset).where(
                    Asset.id.in_(best), permissions.graph_accessible_assets_filter(user)
                )
            )
        ).all()
        frontier = set()
        for asset in sorted(assets, key=lambda a: (best[a.id][0], str(a.id))):
            if added >= MAX_NEIGHBOURS:
                break
            weight, origin, label = best[asset.id]
            via = {"kind": "neighbour", "from": slots[origin].asset.slug, "type": label}
            _add(slots, asset, (G_NEIGHBOUR, level, weight), via)
            frontier.add(asset.id)
            added += 1
        if not frontier:
            break
    return seeds


async def _hidden_count(
    session: AsyncSession, user: User, req: ContextRequest, project: Project
) -> int | None:
    """Linked documents of `project` (home or assigned, ADR-0017) the caller
    has no graph access to. None unless the task has documents in the project,
    so the owner of any project cannot probe foreign tasks."""
    asset_id = distinct(AssetExternalRef.asset_id)
    hidden = not_(permissions.graph_accessible_assets_filter(user))
    linked, hidden_n = (
        await session.execute(
            select(func.count(asset_id), func.count(asset_id).filter(hidden))
            .join(Asset, Asset.id == AssetExternalRef.asset_id)
            .where(_task_filter(req), Asset.deleted_at.is_(None), in_project_filter(project.id))
        )
    ).one()
    return int(hidden_n) if linked else None


async def collect(session: AsyncSession, user: User, req: ContextRequest) -> Collected:
    req.validate()
    project, role = await _resolve_project(session, user, req)
    slots: dict[UUID, Slot] = {}
    context_count, pinned_moved, linked = await _linked(session, user, req, slots)
    if project is not None and context_count < KEY_DOCUMENTS_BELOW:
        await _key_documents(session, user, project, slots)
    await _promote_successors(session, user, slots)
    seeds = await _neighbours(session, user, req, slots)
    hidden = (
        await _hidden_count(session, user, req, project)
        if project is not None and role == "owner"
        else None
    )
    return Collected(
        slots=slots,
        seeds=seeds,
        project=project,
        project_role=role,
        external=req.project if project is not None and project.slug != req.project else None,
        unmapped=bool(req.project) and project is None,
        unlinked=not linked,
        pinned_moved=pinned_moved,
        hidden_count=hidden,
    )
