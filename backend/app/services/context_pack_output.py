"""Agent context pack, second half (ADR-0019): ordering, superseded lines, the
token budget, edges and warnings, in the compact graph shape (ADR-0016). The
budget covers the whole serialised response and is cut from the end of the
ordered list; required documents are never cut. Warnings are data for clients.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetRelation, DocType, User
from app.services.asset_projection import load_metadata, metadata_fields
from app.services.context_pack import (
    G_NEIGHBOUR,
    MAX_BUDGET,
    Collected,
    ContextRequest,
    Slot,
    collect,
)
from app.services.graph_compact import compact_edge, compact_node, drop_shadowed
from app.services.relation_views import estimated_tokens
from app.token_estimate import tokens_for_json
from app.util import now as utc_now

log = structlog.get_logger(__name__)

# Upper bound of the `estimated_tokens` value itself while it is measured.
_ESTIMATE_PLACEHOLDER = 99_999


def _tokens(value: Any) -> int:
    return tokens_for_json(value)


def _full_entry(slot: Slot, fields: dict[str, Any], pinned_moved: bool) -> dict[str, Any]:
    """A listed document with only the fields that are set or not default."""
    a = slot.asset
    flags = list(fields["flags"])
    if pinned_moved and "basis_changed" not in flags:
        flags.append("basis_changed")
    node = {
        "title": a.title,
        "kind": a.kind,
        "doc_type": a.doc_type,
        "freshness": fields["freshness"],
        "summary": fields["summary"],
        "estimated_tokens": estimated_tokens(a),
    }
    entry: dict[str, Any] = {"slug": a.slug, **compact_node(node), "version": a.version}
    if flags:
        entry["flags"] = flags
    if slot.required:
        entry["required"] = True
    entry["via"] = slot.via
    if a.outline_status == "failed":
        entry["has_outline"] = False
    return entry


def _collapsed_entry(slot: Slot, successor: str) -> dict[str, Any]:
    """A superseded document as one line pointing at the slug of its successor."""
    a = slot.asset
    line: dict[str, Any] = {
        "slug": a.slug,
        "title": a.title,
        "freshness": "superseded",
        "collapsed": True,
        "superseded_by": successor,
    }
    if slot.required:
        line["required"] = True
    return line


def _ordered(slots: dict[UUID, Slot]) -> list[tuple[Slot, list[Slot]]]:
    """Full entries in pack order, each with the superseded documents that
    collapsed into it (shown right after it)."""
    lead = [s for s in slots.values() if s.collapsed_into is None]
    lead.sort(key=lambda s: (s.rank, s.asset.title or "", str(s.asset.id)))
    followers: dict[UUID, list[Slot]] = {}
    for s in slots.values():
        if s.collapsed_into is not None:
            followers.setdefault(s.collapsed_into, []).append(s)
    return [(s, sorted(followers.get(s.asset.id, []), key=lambda f: f.rank)) for s in lead]


async def _hints(session: AsyncSession, assets: list[Asset]) -> dict[str, str | None]:
    keys = {a.doc_type for a in assets if a.doc_type}
    if not keys:
        return {}
    rows = await session.execute(
        select(DocType.key, DocType.agent_hint).where(DocType.key.in_(keys))
    )
    return {k: h for k, h in rows.all()}


async def _edges(session: AsyncSession, ids: list[UUID]) -> list[AssetRelation]:
    """Edges between any two candidates, without content links that repeat a
    typed edge; the budget loop keeps those whose both ends are listed."""
    if len(ids) < 2:
        return []
    rows = await session.scalars(
        select(AssetRelation)
        .where(AssetRelation.source_asset_id.in_(ids), AssetRelation.target_asset_id.in_(ids))
        .order_by(AssetRelation.created_at, AssetRelation.id)
    )
    return drop_shadowed(rows.all())


def _doc_warnings(entry: dict[str, Any]) -> list[dict[str, Any]]:
    if entry.get("collapsed"):
        params = {"slug": entry["slug"], "successor": entry["superseded_by"]}
        return [{"code": "superseded", "params": params | {"required": "required" in entry}}]
    if "basis_changed" in entry.get("flags", ()):
        return [{"code": "basis_changed", "params": {"slug": entry["slug"]}}]
    return []


def _edge_warnings(edge: list[Any]) -> list[dict[str, Any]]:
    if edge[1] != "contradicts":
        return []
    return [{"code": "contradicts", "params": {"from": edge[0], "to": edge[2]}}]


@dataclass
class _Candidate:
    slot: Slot
    entry: dict[str, Any]
    # Agent hint of the entry's document type, listed once per type.
    hint: str | None = None
    # Edges to candidates earlier in the pack, serialised.
    edges: list[tuple[UUID, list[Any]]] = field(default_factory=list)

    @property
    def doc_type(self) -> str | None:
        return self.entry.get("doc_type") if self.hint else None

    def cost(self, listed: set[UUID], types: set[str]) -> int:
        """Tokens this entry adds next to the `listed` ones: the entry, its
        warnings, its type's hint when no listed entry has it yet and its
        edges (with their warnings) to listed documents."""
        total = _tokens(self.entry) + _tokens(_doc_warnings(self.entry))
        if self.doc_type and self.doc_type not in types:
            total += _tokens({self.doc_type: self.hint})
        for other, edge in self.edges:
            if other in listed:
                total += _tokens(edge) + _tokens(_edge_warnings(edge))
        return total


def _candidates(
    c: Collected,
    metadata: dict[UUID, Any],
    hints: dict[str, str | None],
    edges: list[AssetRelation],
) -> list[_Candidate]:
    now = utc_now()
    out: list[_Candidate] = []
    for lead, followers in _ordered(c.slots):
        fields = metadata_fields(lead.asset, metadata.get(lead.asset.id), now, preview=True)
        if fields["superseded_by"]:
            # A superseded document whose successor is not in the pack.
            successor = fields["superseded_by"]["slug"]
            out.append(_Candidate(lead, _collapsed_entry(lead, successor)))
        else:
            hint = hints.get(lead.asset.doc_type or "")
            entry = _full_entry(lead, fields, lead.asset.id in c.pinned_moved)
            out.append(_Candidate(lead, entry, hint))
        out += [_Candidate(f, _collapsed_entry(f, lead.asset.slug)) for f in followers]
    position = {cand.slot.asset.id: i for i, cand in enumerate(out)}
    assets = {cand.slot.asset.id: cand.slot.asset for cand in out}
    slug_of = {i: a.slug for i, a in assets.items()}
    for e in edges:
        src, dst = position[e.source_asset_id], position[e.target_asset_id]
        later, earlier = (out[src], out[dst]) if src > dst else (out[dst], out[src])
        later.edges.append(
            (earlier.slot.asset.id, compact_edge(e, slug_of, assets[e.target_asset_id].version))
        )
    return out


def _assemble(
    head: dict[str, Any],
    kept: list[_Candidate],
    truncated: dict[str, Any] | None,
    tail: dict[str, Any],
    unmapped: str | None,
    unlinked: bool,
) -> dict[str, Any]:
    """The response with `kept` listed, its size measured into
    `estimated_tokens`. `unmapped` is the task's project when it maps to no
    ICS project; `unlinked` flags a task with no visible linked document."""
    ids = {cand.slot.asset.id for cand in kept}
    doc_types: dict[str, str] = {}
    for cand in kept:
        if cand.doc_type and cand.hint is not None:
            doc_types.setdefault(cand.doc_type, cand.hint)
    edges = [edge for cand in kept for other, edge in cand.edges if other in ids]
    warnings = [w for cand in kept for w in _doc_warnings(cand.entry)]
    warnings += [w for edge in edges for w in _edge_warnings(edge)]
    if unmapped:
        warnings.append({"code": "project_unmapped", "params": {"project": unmapped}})
    if unlinked:
        # Key documents alone would hide a mistyped work package number.
        task = head["task"]
        warnings.append(
            {"code": "task_unlinked", "params": {"system": task["system"], "wp": task["wp"]}}
        )
    body = head | {
        **({"doc_types": doc_types} if doc_types else {}),
        "documents": [cand.entry for cand in kept],
        "edges": edges,
        "warnings": warnings,
        "truncated": truncated,
        **tail,
    }
    body["estimated_tokens"] = _ESTIMATE_PLACEHOLDER
    body["estimated_tokens"] = _tokens(body)
    return body


def _truncated(
    cut: list[_Candidate], kept: list[_Candidate], c: Collected, needed: int
) -> dict[str, Any] | None:
    """What the budget cut, with what a client needs to get more: the size
    of the uncut pack and, when neighbours were cut, a seed to explore."""
    if not cut:
        return None
    neighbours = sum(1 for cand in cut if cand.slot.rank[0] == G_NEIGHBOUR)
    ids = {cand.slot.asset.id for cand in kept}
    seed = next((c.slots[i].asset.slug for i in c.seeds if i in ids), None)
    return {
        "documents": len(cut) - neighbours,
        "neighbours": neighbours,
        "needed_tokens": needed,
        "max_budget_tokens": MAX_BUDGET,
        "seed": seed if neighbours else None,
    }


async def build(
    session: AsyncSession, user: User, req: ContextRequest, *, transport: str | None = None
) -> dict[str, Any]:
    """The context pack of `req` for `user` (never raises for an unknown or
    hidden task: an empty `documents` list)."""
    c = await collect(session, user, req)
    assets = [s.asset for s in c.slots.values()]
    metadata = await load_metadata(session, assets, user)
    hints = await _hints(session, assets)
    edges = await _edges(session, list(c.slots))
    candidates = _candidates(c, metadata, hints, edges)

    head: dict[str, Any] = {
        "project": (
            {"slug": c.project.slug, "name": c.project.name, "external": c.external}
            if c.project is not None
            else None
        ),
        "task": {"system": req.system, "wp": req.wp, "ancestors": list(req.ancestors)},
    }
    tail: dict[str, Any] = {} if c.hidden_count is None else {"hidden_count": c.hidden_count}
    unmapped = req.project if c.unmapped else None

    # Greedy pass on per-entry costs, then a re-fit on the measured response.
    base = _assemble(head, [], None, tail, unmapped, c.unlinked)["estimated_tokens"]
    used = needed = base
    kept: list[_Candidate] = []
    cut: list[_Candidate] = []
    seen: set[UUID] = set()
    listed: set[UUID] = set()
    seen_types: set[str] = set()
    listed_types: set[str] = set()
    for cand in candidates:
        needed += cand.cost(seen, seen_types)
        seen.add(cand.slot.asset.id)
        cost = cand.cost(listed, listed_types)
        if cand.doc_type:
            seen_types.add(cand.doc_type)
        if not cand.slot.required and (cut or used + cost > req.budget_tokens):
            cut.append(cand)
            continue
        used += cost
        kept.append(cand)
        listed.add(cand.slot.asset.id)
        if cand.doc_type:
            listed_types.add(cand.doc_type)
    while True:
        body = _assemble(head, kept, _truncated(cut, kept, c, needed), tail, unmapped, c.unlinked)
        removable = [i for i, cand in enumerate(kept) if not cand.slot.required]
        if body["estimated_tokens"] <= req.budget_tokens or not removable:
            break
        cut.append(kept.pop(removable[-1]))

    log.info(
        "context_pack_served",
        transport=transport,
        documents=len(kept),
        neighbours=sum(1 for cand in kept if cand.slot.rank[0] == G_NEIGHBOUR),
        hidden=c.hidden_count,
        estimated_tokens=body["estimated_tokens"],
        truncated=bool(cut),
    )
    return body
