"""Watching a project (ADR-0023): any accepted member may watch."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import get_session
from app.services.notifications import watches

from ._router import router
from ._shared import _project_with_min_role


class ProjectWatchIn(BaseModel):
    level: watches.ProjectLevel


@router.get("/{slug}/watch")
async def get_project_watch(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    project, _ = await _project_with_min_role(session, slug, user, "viewer")
    return {"level": await watches.project_level(session, user.id, project.id)}


@router.put("/{slug}/watch")
async def put_project_watch(
    slug: str,
    body: ProjectWatchIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    project, _ = await _project_with_min_role(session, slug, user, "viewer")
    await watches.set_project(session, user.id, project.id, body.level)
    await session.commit()
    return {"level": body.level}


@router.delete("/{slug}/watch")
async def delete_project_watch(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    project, _ = await _project_with_min_role(session, slug, user, "viewer")
    await watches.clear_project(session, user.id, project.id)
    await session.commit()
    return {"level": None}
