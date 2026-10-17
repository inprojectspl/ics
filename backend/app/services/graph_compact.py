"""Compact graph shape for agents (ADR-0016, section 10): nodes keyed by slug
without defaults or nulls, and edges as `[from, type, to]` triples with an
optional fourth element for non-default extras. The graph endpoints default to
the verbose shape the web client reads; the context pack is compact only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal
from uuid import UUID

from app.models import AssetRelation
from app.services.asset_projection import cut_text

Shape = Literal["full", "compact"]
# Long enough to decide whether to open a document, short enough for 20 nodes.
SUMMARY_CHARS = 200
DEFAULT_KIND = "md_single"


def short_summary(summary: str | None) -> str | None:
    return cut_text(summary, SUMMARY_CHARS)


def compact_node(node: Mapping[str, Any], *, summary: bool = True) -> dict[str, Any]:
    """A `relation_views.project_nodes` entry without its slug (the key),
    ids, nulls and default values."""
    out: dict[str, Any] = {"title": node.get("title")}
    if node.get("kind") and node["kind"] != DEFAULT_KIND:
        out["kind"] = node["kind"]
    if node.get("doc_type"):
        out["doc_type"] = node["doc_type"]
    if node.get("freshness") and node["freshness"] != "current":
        out["freshness"] = node["freshness"]
    successor = node.get("superseded_by")
    if successor and successor.get("slug"):
        out["superseded_by"] = successor["slug"]
    if summary and (text := short_summary(node.get("summary"))):
        out["summary"] = text
    if node.get("estimated_tokens") is not None:
        out["estimated_tokens"] = node["estimated_tokens"]
    return out


def _is_link(edge: AssetRelation) -> bool:
    return edge.origin == "extracted" and edge.relation_type == "references"


def _pair(edge: AssetRelation) -> frozenset[UUID]:
    return frozenset((edge.source_asset_id, edge.target_asset_id))


def other_end(edge: AssetRelation, asset_id: UUID) -> UUID:
    """The end of `edge` that is not `asset_id`."""
    return edge.target_asset_id if edge.source_asset_id == asset_id else edge.source_asset_id


def drop_shadowed(edges: Iterable[AssetRelation]) -> list[AssetRelation]:
    """Edges without the `references` extracted from a content link when a
    typed or explicit edge joins the same two documents: the link is how the
    author expressed that relation, so the agent sees it once."""
    edges = list(edges)
    explicit = {_pair(e) for e in edges if not _is_link(e)}
    return [e for e in edges if not (_is_link(e) and _pair(e) in explicit)]


def edge_changed(edge: AssetRelation, target_version_now: int | None) -> bool:
    return (
        edge.target_version is not None
        and target_version_now is not None
        and target_version_now > edge.target_version
    )


def compact_edge(
    edge: AssetRelation,
    slug_of: Mapping[UUID, str],
    target_version_now: int | None,
    *,
    with_id: bool = False,
) -> list[Any]:
    """`[from, type, to]`, plus `{id, source_path, target_path, target_anchor,
    note, changed}` holding only what is set; `changed` is `[recorded, now]`."""
    triple: list[Any] = [
        slug_of[edge.source_asset_id],
        edge.relation_type,
        slug_of[edge.target_asset_id],
    ]
    extra: dict[str, Any] = {}
    if with_id:
        extra["id"] = str(edge.id)
    for key in ("source_path", "target_path", "target_anchor", "note"):
        if value := getattr(edge, key):
            extra[key] = value
    if edge_changed(edge, target_version_now):
        extra["changed"] = [edge.target_version, target_version_now]
    if extra:
        triple.append(extra)
    return triple
