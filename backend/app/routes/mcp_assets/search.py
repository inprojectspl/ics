"""Full-text snippet search over `Asset.search_tsv`. Visibility uses
`permissions.visible_assets_filter`, like `/index` (see
`test_visibility_parity.py`)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Query
from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.db import get_session
from app.json_response import ORJSONResponse
from app.models import Asset, User
from app.pdf_markdown import snippet_probe
from app.services import doc_types, graph_signals
from app.services.asset_projection import preview_summary
from app.services.document_search import (
    SEARCH_CONFIG,
    SearchMatch,
    build_tsquery,
    query_expression,
    search_filter,
    search_score,
)
from app.services.freshness import FilterableFreshness
from app.services.freshness import freshness as freshness_of
from app.services.project_shares import in_project_filter
from app.services.read_size import estimated_tokens
from app.util import now as utc_now

from ._models import SearchHit, SearchPage, SearchSnippet
from ._router import router
from ._shared import metadata_filters

_START_SEL, _STOP_SEL = "<em>", "</em>"
_HEADLINE_OPTS = (
    f"MaxFragments=3, MinWords=5, MaxWords=20, StartSel={_START_SEL}, StopSel={_STOP_SEL}"
)


async def _snippet_position(
    session: AsyncSession, asset_id: UUID, snippet: str, separator: str
) -> int | None:
    """1-based page (form feed, PDF) or line (newline, md_single) of a
    snippet, computed in the database so the text never leaves it. None
    when the snippet comes from the title or summary only."""
    probe = snippet_probe(snippet, start_sel=_START_SEL, stop_sel=_STOP_SEL)
    if probe is None:
        return None
    pattern, word = probe
    # substring + strpos instead of `regexp_instr`, which needs PostgreSQL 15.
    matched = func.substring(Asset.search_content, pattern)
    pos = func.coalesce(
        func.nullif(func.strpos(Asset.search_content, matched), 0),
        func.nullif(func.strpos(Asset.search_content, word), 0),
    )
    before = func.left(Asset.search_content, pos - 1)
    position = func.length(before) - func.length(func.replace(before, separator, "")) + 1
    return await session.scalar(select(position).where(Asset.id == asset_id))


def _matching_assets_select(
    user: User,
    q: str,
    match: SearchMatch,
    kind: list[str] | None,
    project_id: UUID | None,
    filters: Sequence[Any] = (),
):
    """SELECT of visible assets matching the tsquery: the shared base for the
    result page and the overshoot COUNT (one definition, so the filters
    can't drift apart)."""
    stmt = select(
        Asset.id,
        Asset.slug,
        Asset.title,
        Asset.kind,
        func.coalesce(Asset.content_updated_at, Asset.updated_at).label("changed_at"),
        search_score(q, user, match).label("score"),
    ).where(
        permissions.visible_assets_filter(user),
        search_filter(q, match),
        *filters,
    )
    if kind:
        stmt = stmt.where(Asset.kind.in_(kind))
    if project_id is not None:
        stmt = stmt.where(in_project_filter(project_id))
    return stmt


@router.get("/search-mcp", response_model=SearchPage)
async def search_with_snippets(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    match: SearchMatch = "all",
    kind: Annotated[list[str] | None, Query()] = None,
    project_id: UUID | None = None,
    tag: Annotated[list[str] | None, Query()] = None,
    doc_type: Annotated[list[str] | None, Query()] = None,
    freshness: Annotated[list[FilterableFreshness] | None, Query()] = None,
    maintainer: UUID | None = None,
) -> ORJSONResponse:
    """Shared document matching and relevance, with page-local snippets.

    Stable order: relevance, content change time, id; concurrent edits can
    still reorder offset pages.
    """
    if doc_type:
        await doc_types.check_filter_keys(session, doc_type)
    tsq = build_tsquery(q, match)

    rows: Sequence[Row[Any]] = []
    total = 0
    if tsq is not None:
        tsquery = query_expression(q, match)
        filters = metadata_filters(
            doc_type=doc_type,
            freshness=freshness,
            tag=tag,
            maintainer=maintainer,
            now=utc_now(),
            viewer=user,
        )
        matching = _matching_assets_select(user, q, match, kind, project_id, filters)
        visible = matching.cte("visible")

        score = visible.c.score
        page = (
            select(
                visible.c.id,
                visible.c.slug,
                visible.c.title,
                visible.c.kind,
                visible.c.changed_at,
                score,
                func.count().over().label("total_count"),
            )
            .order_by(score.desc(), visible.c.changed_at.desc(), visible.c.id.asc())
            .limit(limit)
            .offset(offset)
        ).cte("page")

        headline = func.ts_headline(
            SEARCH_CONFIG,
            func.concat_ws(
                " ",
                Asset.title,
                Asset.summary,
                func.ics_immutable_array_to_string(Asset.tags, " "),
                Asset.search_content,
            ),
            tsquery,
            _HEADLINE_OPTS,
        ).label("snippet")
        stmt = (
            select(
                page.c.id,
                page.c.slug,
                page.c.title,
                page.c.kind,
                page.c.score,
                page.c.total_count,
                headline,
                Asset.summary,
                Asset.doc_type,
                Asset.review_due_at,
                Asset.entry_path,
                Asset.read_tokens,
                Asset.size_bytes,
                graph_signals.visible_successor_exists(user, page.c.id).label("superseded"),
            )
            .join_from(page, Asset, Asset.id == page.c.id)
            .order_by(page.c.score.desc(), page.c.changed_at.desc(), page.c.id.asc())
        )
        rows = (await session.execute(stmt)).all()

        if rows:
            total = int(rows[0].total_count)
        elif offset:
            # Past the last page there is no window count to read the total from.
            count_stmt = select(func.count()).select_from(matching.subquery())
            total = int((await session.execute(count_stmt)).scalar() or 0)

    superseded = {row.id for row in rows if row.superseded}
    successors = await graph_signals.latest_successors(session, user, superseded)
    ends = await graph_signals.chain_ends(session, user, successors)

    items = []
    now = utc_now()
    for row in rows:
        snippet_text = row.snippet or ""
        snippet_page = snippet_line = None
        if row.kind == "pdf_doc" and snippet_text:
            snippet_page = await _snippet_position(session, row.id, snippet_text, "\f")
        elif row.kind == "md_single" and snippet_text:
            snippet_line = await _snippet_position(session, row.id, snippet_text, "\n")
        snippets = (
            # The form feed only separates PDF pages in the blob; a snippet
            # across a page break shows it as the blank line around it.
            [
                SearchSnippet(
                    path=row.entry_path if snippet_line is not None else None,
                    line=snippet_line,
                    text=snippet_text.replace("\f", ""),
                    page=snippet_page,
                )
            ]
            if snippet_text.strip()
            else []
        )
        items.append(
            SearchHit(
                id=row.id,
                slug=row.slug,
                title=row.title,
                kind=row.kind,
                score=float(row.score or 0.0),
                summary=preview_summary(row.summary),
                doc_type=row.doc_type,
                freshness=freshness_of(row, now, superseded=bool(row.superseded)),
                latest=ends[row.id].slug if row.id in ends else None,
                estimated_tokens=estimated_tokens(row),
                snippets=snippets,
            )
        )
    page_out = SearchPage(
        items=items,
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + len(items) < total,
    )
    return ORJSONResponse(page_out.model_dump(mode="json"))
