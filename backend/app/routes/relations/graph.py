"""Graph traversal endpoints (ADR-0016, section 6)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.db import get_session
from app.domain_errors import InvalidInputError
from app.models import Project, ProjectMember
from app.routes.projects._shared import _project_with_min_role
from app.services.graph_compact import Shape
from app.services.graph_path import MAX_PROJECTS, MAX_STARTS, find_path
from app.services.project_graph import MAX_PROJECT_NODES, project_graph
from app.services.relation_graph import MAX_DEPTH, MAX_NODES, neighbourhood
from app.services.relation_views import Direction
from app.services.relations import RELATION_TYPE_SET

from ._router import router


@router.get("/assets/by-slug/{slug}/neighbourhood")
async def get_neighbourhood(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    depth: Annotated[int, Query(ge=1, le=MAX_DEPTH)] = 1,
    types: Annotated[list[str] | None, Query()] = None,
    max_nodes: Annotated[int, Query(ge=1, le=MAX_NODES)] = MAX_NODES,
    direction: Direction = "both",
    shape: Shape = "full",
) -> dict:
    """`shape=compact` is the agent format (ADR-0016, section 10)."""
    asset = await permissions.get_graph_asset(session, user, slug=slug)
    return await neighbourhood(
        session,
        user,
        asset,
        depth=depth,
        types=types,
        max_nodes=max_nodes,
        direction=direction,
        shape=shape,
    )


class GraphPathIn(BaseModel):
    """What the graph explorer shows: documents by id, projects by slug."""

    model_config = ConfigDict(populate_by_name=True)

    start: list[UUID] = Field(default_factory=list, alias="from", max_length=MAX_STARTS)
    projects: list[str] = Field(default_factory=list, max_length=MAX_PROJECTS)
    types: list[str] | None = None


@router.post("/assets/by-slug/{slug}/path")
async def post_graph_path(
    slug: str,
    body: GraphPathIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Shortest walk from documents or projects the graph explorer already
    shows to this document, over `types` (every type by default); `path` is
    null when there is none. A POST because the list of documents on screen
    does not fit a URL. Projects the caller is not a member of are ignored."""
    target, _role = await permissions.get_asset_with_role(
        session, user=user, min_role="viewer", slug=slug
    )
    wanted = set(body.types) if body.types else set(RELATION_TYPE_SET)
    if not wanted <= RELATION_TYPE_SET:
        raise InvalidInputError("relation_type_invalid", "unknown relation type")
    projects: list[Project] = []
    if body.projects:
        # One statement: the caller's projects among the slugs (any project for an acting admin).
        stmt = select(Project).where(Project.slug.in_(body.projects), Project.deleted_at.is_(None))
        if not user.acts_as_admin:
            stmt = stmt.join(
                ProjectMember,
                (ProjectMember.project_id == Project.id)
                & (ProjectMember.user_id == user.id)
                & ProjectMember.accepted_at.is_not(None),
            )
        by_slug = {p.slug: p for p in (await session.scalars(stmt)).all()}
        projects = [by_slug[s] for s in body.projects if s in by_slug]
    path = await find_path(
        session, user, target, starts=body.start, projects=projects, types=wanted
    )
    return {"path": path}


@router.get("/projects/{slug}/graph")
async def get_project_graph(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    include: Annotated[list[Literal["tasks"]] | None, Query()] = None,
    max_nodes: Annotated[int, Query(ge=1, le=MAX_PROJECT_NODES)] = MAX_PROJECT_NODES,
) -> dict:
    """Documents of the project and their relations; any member (viewer
    included) and admin, everyone else 404."""
    project, _role = await _project_with_min_role(session, slug, user, "viewer")
    return await project_graph(
        session, user, project, include_tasks="tasks" in (include or []), max_nodes=max_nodes
    )
