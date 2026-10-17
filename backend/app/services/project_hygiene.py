"""Hygiene lists of a project (ADR-0015, ADR-0016); the caller has checked the
viewer is a project owner, editor or admin. All counters come from one
statement. `hidden_edges` exposes only a count, nothing about those documents.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, get_args

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app import permissions
from app.models import Asset, AssetExternalRef, AssetRelation, Project, User
from app.services import duplicate_suggestions, graph_signals
from app.services.project_shares import in_project_filter
from app.util import now as utc_now

HygieneList = Literal[
    "no_summary",
    "summary_stale",
    "no_doc_type",
    "review_overdue",
    "basis_changed",
    "superseded_linked",
    "hidden_edges",
    "duplicates",
]
HYGIENE_LISTS: tuple[str, ...] = get_args(HygieneList)
# Lists whose counter is not a count of documents matching a condition.
_PAIR_OR_EDGE_LISTS = frozenset({"hidden_edges", "duplicates"})
PAGE_SIZE = 25

# Project documents are the outer rows; `Asset` stays free for the inner
# "other end" lookups so `visible_assets_filter` correlates to them.
Doc = aliased(Asset, name="doc")


def _in_project(project_id: Any, doc: Any = Doc) -> ColumnElement[bool]:
    return and_(doc.deleted_at.is_(None), in_project_filter(project_id, doc))


def _hidden_targets(user: User) -> ColumnElement[bool]:
    """The edge's target exists (not deleted) but the viewer cannot read it."""
    return exists(
        select(Asset.id).where(
            Asset.id == AssetRelation.target_asset_id,
            Asset.deleted_at.is_(None),
            ~permissions.visible_assets_filter(user),
        )
    )


def _conditions(user: User, now: datetime) -> dict[str, ColumnElement[bool]]:
    # A hidden basis or successor never shows up in a list (ADR-0015).
    basis_changed = graph_signals.changed_basis_exists(user, Doc.id)
    superseded = graph_signals.visible_successor_exists(user, Doc.id)
    linked = exists(select(AssetExternalRef.id).where(AssetExternalRef.asset_id == Doc.id))
    hidden = exists(
        select(AssetRelation.id).where(
            AssetRelation.source_asset_id == Doc.id, _hidden_targets(user)
        )
    )
    return {
        "no_summary": or_(Doc.summary.is_(None), func.trim(Doc.summary) == ""),
        "summary_stale": and_(
            Doc.summary.is_not(None),
            Doc.summary_version.is_not(None),
            Doc.summary_version < Doc.version,
        ),
        "no_doc_type": Doc.doc_type.is_(None),
        "review_overdue": Doc.review_due_at < now,
        "basis_changed": basis_changed,
        "superseded_linked": and_(superseded, linked),
        "hidden_edges": hidden,
    }


def _hidden_edge_count(project_id: Any, user: User):
    # Own alias: `Doc` would correlate to the outer counters query.
    source = aliased(Asset, name="hidden_source")
    project_docs = select(source.id).where(_in_project(project_id, source))
    return (
        select(func.count())
        .select_from(AssetRelation)
        .where(AssetRelation.source_asset_id.in_(project_docs), _hidden_targets(user))
        .scalar_subquery()
    )


async def counters(session: AsyncSession, user: User, project: Project) -> dict[str, int]:
    """Size of every list, in one statement. `hidden_edges` counts edges,
    `duplicates` pairs, the other lists count documents."""
    conds = _conditions(user, utc_now())
    columns = [
        func.count().filter(conds[name]).label(name)
        for name in HYGIENE_LISTS
        if name not in _PAIR_OR_EDGE_LISTS
    ]
    row = (
        await session.execute(
            select(
                *columns,
                _hidden_edge_count(project.id, user).label("hidden_edges"),
                duplicate_suggestions.count_query(project.id).label("duplicates"),
            )
            .select_from(Doc)
            .where(_in_project(project.id))
        )
    ).one()
    return {name: int(getattr(row, name) or 0) for name in HYGIENE_LISTS}


async def page(
    session: AsyncSession, user: User, project: Project, name: HygieneList, page_no: int
) -> list[dict[str, Any]]:
    """One page of list `name`: documents ordered by title, or for
    `duplicates` suggested pairs, certain ones first."""
    offset = (page_no - 1) * PAGE_SIZE
    if name == "duplicates":
        return await duplicate_suggestions.page(session, project, limit=PAGE_SIZE, offset=offset)
    conds = _conditions(user, utc_now())
    hidden_per_doc = (
        select(func.count())
        .select_from(AssetRelation)
        .where(AssetRelation.source_asset_id == Doc.id, _hidden_targets(user))
        .scalar_subquery()
    )
    columns: list[Any] = [Doc]
    if name == "hidden_edges":
        columns.append(hidden_per_doc.label("hidden_count"))
    rows = (
        await session.execute(
            select(*columns)
            .where(_in_project(project.id), conds[name])
            .order_by(Doc.title, Doc.id)
            .limit(PAGE_SIZE)
            .offset(offset)
        )
    ).all()
    out = []
    for row in rows:
        a: Asset = row[0]
        item: dict[str, Any] = {
            "id": str(a.id),
            "slug": a.slug,
            "title": a.title,
            "kind": a.kind,
            "doc_type": a.doc_type,
            "version": a.version,
            "summary_version": a.summary_version,
            "review_due_at": a.review_due_at.isoformat() if a.review_due_at else None,
            "content_updated_at": (
                a.content_updated_at.isoformat() if a.content_updated_at else None
            ),
        }
        if name == "hidden_edges":
            item["hidden_edges"] = int(row[1])
        out.append(item)
    return out
