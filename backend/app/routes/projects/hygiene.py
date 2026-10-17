"""Project hygiene lists: documents that need attention (owners, editors)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.db import get_session
from app.errors import ApiError
from app.models import Project, User
from app.routes.relations._shared import transport_of
from app.services import duplicate_suggestions, project_hygiene
from app.services.project_hygiene import PAGE_SIZE, HygieneList

from ._router import router
from ._shared import _project_with_min_role


class DuplicatePairIn(BaseModel):
    source_id: UUID
    target_id: UUID


async def _maintainable_project(session: AsyncSession, slug: str, user: User) -> Project:
    """Project owners, editors and admins; a viewer gets a stranger's 404."""
    project, role = await _project_with_min_role(session, slug, user, "viewer")
    rank = permissions.MEMBER_ROLE_RANK
    if rank[role] < rank["editor"]:
        raise ApiError(status.HTTP_404_NOT_FOUND, "project_not_found", "project not found")
    return project


@router.get("/{slug}/hygiene")
async def get_project_hygiene(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    list_name: Annotated[HygieneList, Query(alias="list")] = "no_summary",
    page: Annotated[int, Query(ge=1)] = 1,
) -> dict:
    """Counters of every list plus one page of `list`. A viewer gets the same
    404 as a stranger: the lists are a maintenance tool, not reading."""
    project = await _maintainable_project(session, slug, user)
    counters = await project_hygiene.counters(session, user, project)
    items = await project_hygiene.page(session, user, project, list_name, page)
    return {
        "project": {"id": str(project.id), "slug": project.slug, "name": project.name},
        "counters": counters,
        "list": list_name,
        "page": page,
        "page_size": PAGE_SIZE,
        "total": counters[list_name],
        "items": items,
    }


@router.post("/{slug}/hygiene/duplicates/mark", status_code=status.HTTP_201_CREATED)
async def mark_duplicate(
    slug: str,
    body: DuplicatePairIn,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Accept a suggestion: `source duplicates target` as a manual relation."""
    project = await _maintainable_project(session, slug, user)
    edge = await duplicate_suggestions.mark_duplicate(
        session,
        project=project,
        actor=user,
        source_id=body.source_id,
        target_id=body.target_id,
        **transport_of(request),
    )
    await session.commit()
    return {"relation_id": str(edge.id)}


@router.post("/{slug}/hygiene/duplicates/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_duplicate(
    slug: str,
    body: DuplicatePairIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Reject a suggestion ("not a duplicate"): the pair is not suggested again."""
    project = await _maintainable_project(session, slug, user)
    await duplicate_suggestions.dismiss(
        session, project=project, actor=user, first=body.source_id, second=body.target_id
    )
    await session.commit()
