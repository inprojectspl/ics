"""Shortest walk in the relation graph from the cards a reader already has in
the graph explorer to one document (ADR-0025). Every hop needs graph access,
the same rule the neighbourhood applies, so a path through a document the
reader cannot open does not exist. Client start ids only end the search.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import select, union
from sqlalchemy.engine import Result
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetProjectShare, Project, User
from app.services.relation_graph import edges_touching
from app.services.relations import graph_access_ids

MAX_PATH_DEPTH = 6
MAX_STARTS = 500
MAX_PROJECTS = 50
# Bounds the work of a search that finds nothing in a dense graph.
MAX_VISITED = 4000


async def _held_by(
    session: AsyncSession, projects: Sequence[Project], ids: Collection[UUID]
) -> tuple[Project, UUID] | None:
    """The first project (in the given order) holding one of `ids`, with
    that id. One statement for every project: home assets and assets
    assigned to a project, like `in_project_filter`."""
    if not ids or not projects:
        return None
    wanted = list(ids)
    by_project = [p.id for p in projects]
    rows: Result[Any] = await session.execute(
        union(
            select(Asset.id, Asset.project_id).where(
                Asset.id.in_(wanted), Asset.project_id.in_(by_project)
            ),
            select(AssetProjectShare.asset_id, AssetProjectShare.project_id).where(
                AssetProjectShare.asset_id.in_(wanted),
                AssetProjectShare.project_id.in_(by_project),
            ),
        )
    )
    held: dict[UUID, list[UUID]] = {}
    for asset_id, project_id in rows.all():
        held.setdefault(project_id, []).append(asset_id)
    for project in projects:
        if project.id in held:
            return project, min(held[project.id], key=str)
    return None


def _chain(towards: dict[UUID, UUID], start: UUID) -> list[UUID]:
    """Ids from `start` to the target, following the next hop of each."""
    out = [start]
    while towards[out[-1]] != out[-1]:
        out.append(towards[out[-1]])
    return out


async def _materialise(
    session: AsyncSession, ids: list[UUID], project: Project | None
) -> list[dict[str, Any]]:
    rows = (await session.scalars(select(Asset).where(Asset.id.in_(ids)))).all()
    by_id = {a.id: a for a in rows}
    path: list[dict[str, Any]] = []
    if project is not None:
        path.append({"kind": "project", "id": str(project.id), "slug": project.slug})
    for i in ids:
        a = by_id[i]
        path.append({"kind": "doc", "id": str(a.id), "slug": a.slug, "title": a.title})
    return path


async def find_path(
    session: AsyncSession,
    actor: User,
    target: Asset,
    *,
    starts: Collection[UUID],
    projects: Sequence[Project],
    types: Collection[str],
) -> list[dict[str, Any]] | None:
    """Steps from a start (a document id in `starts`, or a project of
    `projects` holding the first document) to `target`, which the caller
    has checked the actor can read; None when no walk of at most
    `MAX_PATH_DEPTH` hops over `types` exists."""
    start_set = set(starts)

    async def hit(towards: dict[UUID, UUID], reached: set[UUID]) -> list[dict[str, Any]] | None:
        """The path when `reached` holds a start or a project's document."""
        starts_hit = sorted(reached & start_set, key=str)
        if starts_hit:
            return await _materialise(session, _chain(towards, starts_hit[0]), None)
        held = await _held_by(session, projects, reached)
        if held:
            return await _materialise(session, _chain(towards, held[1]), held[0])
        return None

    towards: dict[UUID, UUID] = {target.id: target.id}
    frontier = {target.id}
    if found_path := await hit(towards, frontier):
        return found_path
    for _ in range(MAX_PATH_DEPTH):
        found: dict[UUID, UUID] = {}
        for e in await edges_touching(session, frontier, types):
            for here, there in (
                (e.source_asset_id, e.target_asset_id),
                (e.target_asset_id, e.source_asset_id),
            ):
                if here in frontier and there not in towards and there not in found:
                    found[there] = here
        if not found:
            return None
        reachable = await graph_access_ids(session, actor, found)
        for node in reachable:
            towards[node] = found[node]
        if found_path := await hit(towards, reachable):
            return found_path
        if len(towards) > MAX_VISITED:
            return None
        frontier = reachable
    return None
