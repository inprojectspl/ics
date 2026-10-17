"""Links from a document to tasks in external systems (ADR-0018)."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import Depends, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import get_session
from app.models import Asset
from app.routes.projects._shared import _project_with_min_role
from app.services import external_refs as external_refs_svc

from ._router import router
from ._shared import transport_of


class AddExternalRefIn(BaseModel):
    # Plain strings: the service answers `external_ref_invalid`, not a 422.
    system: str = Field(max_length=32)
    entity: str = Field(max_length=32)
    external_id: str = Field(max_length=200)
    external_scope: str | None = Field(default=None, max_length=100)
    role: str = Field(default="context", max_length=16)
    required: bool = False
    label: str | None = Field(default=None, max_length=1000)
    url: str | None = Field(default=None, max_length=2048)
    asset_path: str | None = Field(default=None, max_length=1024)
    pinned_version: int | None = None
    note: str | None = Field(default=None, max_length=500)


class NodeKeyIn(BaseModel):
    system: Literal["project_standard"]
    external_scope: str = Field(max_length=100)
    external_id: str = Field(max_length=200)


class WorkPackageKeyIn(BaseModel):
    system: Literal["openproject"]
    entity: Literal["work_package"] = "work_package"
    external_id: str = Field(max_length=200)


class RekeyIn(BaseModel):
    project_slug: str
    from_: NodeKeyIn = Field(alias="from")
    to: WorkPackageKeyIn


@router.post("/external-refs/rekey")
async def rekey_external_refs(
    body: RekeyIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Project owner only; counts cover only links the caller could move."""
    project, _ = await _project_with_min_role(session, body.project_slug, user, "owner")
    counts = await external_refs_svc.rekey_node_to_work_package(
        session,
        actor=user,
        project=project,
        node_scope=body.from_.external_scope,
        node_id=body.from_.external_id,
        work_package_id=body.to.external_id,
    )
    await session.commit()
    return counts


@router.get("/assets/{asset_id}/external-refs")
async def list_external_refs(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[dict]:
    return await external_refs_svc.list_refs(session, actor=user, asset_id=asset_id)


@router.post("/assets/{asset_id}/external-refs", status_code=status.HTTP_201_CREATED)
async def add_external_ref(
    asset_id: UUID,
    body: AddExternalRefIn,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    ref = await external_refs_svc.add_ref(
        session, actor=user, asset_id=asset_id, **body.model_dump(), **transport_of(request)
    )
    await session.commit()
    asset = await session.get(Asset, asset_id)
    return external_refs_svc.ref_fields(ref, asset.version if asset else 0)


@router.get("/external-refs/{ref_id}")
async def get_external_ref(
    ref_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    return await external_refs_svc.get_ref(session, actor=user, ref_id=ref_id)


@router.delete("/external-refs/{ref_id}")
async def delete_external_ref(
    ref_id: UUID,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    await external_refs_svc.remove_ref(session, actor=user, ref_id=ref_id, **transport_of(request))
    await session.commit()
    return {"deleted": True}
