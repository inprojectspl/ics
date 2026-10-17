"""Project level links (ADR-0018): external project mapping and key documents.

Registered on the relations router, which main.py includes before the
projects router, so `/api/projects/by-external` is not taken for a slug.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import get_session
from app.routes.projects._shared import _project_row, _project_with_min_role
from app.services import project_links as project_links_svc

from ._router import router


class ProjectExternalRefIn(BaseModel):
    system: str = Field(max_length=32)
    external_id: str = Field(max_length=100)


class PutProjectExternalRefsIn(BaseModel):
    refs: list[ProjectExternalRefIn] = Field(max_length=20)


class KeyDocumentIn(BaseModel):
    asset_id: UUID
    reason: str | None = Field(default=None, max_length=300)


class PutKeyDocumentsIn(BaseModel):
    documents: list[KeyDocumentIn] = Field(max_length=20)


@router.get("/projects/by-external")
async def project_by_external(
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    system: Annotated[Literal["openproject", "project_standard"], Query()],
    id: Annotated[str, Query(max_length=100)],
) -> dict:
    project, role = await project_links_svc.project_by_external(
        session, actor=user, system=system, external_id=id
    )
    return _project_row(project, my_role=role)


@router.get("/projects/{slug}/external-refs")
async def get_project_external_refs(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    project, _ = await _project_with_min_role(session, slug, user, "viewer")
    return await project_links_svc.list_external_refs(session, project)


@router.put("/projects/{slug}/external-refs")
async def put_project_external_refs(
    slug: str,
    body: PutProjectExternalRefsIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    project, _ = await _project_with_min_role(session, slug, user, "owner")
    await project_links_svc.set_external_refs(
        session,
        actor=user,
        project=project,
        refs=[(r.system, r.external_id) for r in body.refs],
    )
    await session.commit()
    return await project_links_svc.list_external_refs(session, project)


@router.get("/projects/{slug}/key-documents")
async def get_key_documents(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    project, _ = await _project_with_min_role(session, slug, user, "viewer")
    return await project_links_svc.list_key_documents(session, actor=user, project=project)


@router.put("/projects/{slug}/key-documents")
async def put_key_documents(
    slug: str,
    body: PutKeyDocumentsIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    project, _ = await _project_with_min_role(session, slug, user, "owner")
    await project_links_svc.set_key_documents(
        session,
        actor=user,
        project=project,
        documents=[
            project_links_svc.KeyDocumentIn(asset_id=d.asset_id, reason=d.reason)
            for d in body.documents
        ],
    )
    await session.commit()
    return await project_links_svc.list_key_documents(session, actor=user, project=project)
