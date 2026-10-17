"""Duplicate suggestions in a project (hygiene list `duplicates`): `certain`
pairs share `Asset.content_hash`, `candidate` pairs have similar titles
(pg_trgm above 0.6) and the same doc type. Listing never writes; an edge
appears only through `mark_duplicate`, like any manual relation.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import (
    Select,
    and_,
    case,
    exists,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain_errors import InvalidInputError, NotFoundError
from app.models import (
    Asset,
    AssetRelation,
    DuplicateDismissal,
    Project,
    User,
)
from app.services import relations
from app.services.project_shares import in_project_filter

TITLE_SIMILARITY = 0.6


def _project_docs(project_id: Any):
    """Project documents with the hash of their normalised text."""
    doc = aliased(Asset, name="dup_doc")
    return (
        select(
            doc.id,
            doc.slug,
            doc.title,
            doc.doc_type,
            func.lower(doc.title).label("title_lower"),
            doc.content_hash,
        )
        .where(
            doc.deleted_at.is_(None),
            in_project_filter(project_id, doc),
        )
        .cte("dup_docs")
    )


def pairs_query(project_id: Any) -> Select:
    """Suggested pairs, `a.id < b.id`, certain ones first."""
    docs = _project_docs(project_id)
    a, b = docs.alias("dup_a"), docs.alias("dup_b")
    certain = and_(a.c.content_hash.is_not(None), a.c.content_hash == b.c.content_hash)
    similarity = func.similarity(a.c.title_lower, b.c.title_lower)
    similar = and_(
        a.c.doc_type.is_not_distinct_from(b.c.doc_type),
        # `%` lets the trigram index prune before the exact threshold.
        a.c.title_lower.op("%")(b.c.title_lower),
        similarity > TITLE_SIMILARITY,
    )
    dismissed = exists().where(
        DuplicateDismissal.asset_a_id == a.c.id, DuplicateDismissal.asset_b_id == b.c.id
    )
    linked = exists().where(
        AssetRelation.relation_type == "duplicates",
        or_(
            and_(AssetRelation.source_asset_id == a.c.id, AssetRelation.target_asset_id == b.c.id),
            and_(AssetRelation.source_asset_id == b.c.id, AssetRelation.target_asset_id == a.c.id),
        ),
    )
    return (
        select(
            a.c.id.label("a_id"),
            a.c.slug.label("a_slug"),
            a.c.title.label("a_title"),
            b.c.id.label("b_id"),
            b.c.slug.label("b_slug"),
            b.c.title.label("b_title"),
            case((certain, literal("certain")), else_=literal("candidate")).label("certainty"),
            func.coalesce(similarity, 0).label("similarity"),
        )
        .select_from(a)
        .join(b, a.c.id < b.c.id)
        .where(or_(certain, similar), ~dismissed, ~linked)
    )


def count_query(project_id: Any):
    """Number of suggested pairs, as a scalar subquery for the counters."""
    return select(func.count()).select_from(pairs_query(project_id).subquery()).scalar_subquery()


async def page(
    session: AsyncSession, project: Project, *, limit: int, offset: int
) -> list[dict[str, Any]]:
    pairs = pairs_query(project.id).subquery()
    rows = await session.execute(
        select(pairs)
        .order_by(
            (pairs.c.certainty == "certain").desc(),
            pairs.c.similarity.desc(),
            pairs.c.a_title,
            pairs.c.a_id,
            pairs.c.b_id,
        )
        .limit(limit)
        .offset(offset)
    )
    return [
        {
            "certainty": r.certainty,
            "similarity": round(float(r.similarity), 3),
            "a": {"id": str(r.a_id), "slug": r.a_slug, "title": r.a_title},
            "b": {"id": str(r.b_id), "slug": r.b_slug, "title": r.b_title},
        }
        for r in rows.all()
    ]


async def _project_pair(
    session: AsyncSession, project: Project, first: UUID, second: UUID
) -> tuple[UUID, UUID]:
    """The pair ordered `a < b`, both documents of the project."""
    if first == second:
        raise InvalidInputError("relation_self", "an asset cannot relate to itself")
    docs = _project_docs(project.id)
    found = set(await session.scalars(select(docs.c.id).where(docs.c.id.in_([first, second]))))
    if found != {first, second}:
        raise NotFoundError("asset_not_found", "asset not found")
    return (first, second) if first < second else (second, first)


async def dismiss(
    session: AsyncSession, *, project: Project, actor: User, first: UUID, second: UUID
) -> None:
    """Remember "not a duplicate" for the pair. Idempotent; does not commit."""
    a, b = await _project_pair(session, project, first, second)
    await session.execute(
        insert(DuplicateDismissal)
        .values(asset_a_id=a, asset_b_id=b, dismissed_by=actor.id)
        .on_conflict_do_nothing()
    )


async def mark_duplicate(
    session: AsyncSession,
    *,
    project: Project,
    actor: User,
    source_id: UUID,
    target_id: UUID,
    transport: str | None = None,
    client_id_external: str | None = None,
) -> AssetRelation:
    """`source duplicates target`, as a relation the actor adds by hand."""
    await _project_pair(session, project, source_id, target_id)
    return await relations.add_relation(
        session,
        actor=actor,
        source_id=source_id,
        relation_type="duplicates",
        target_id=target_id,
        transport=transport,
        client_id_external=client_id_external,
    )
