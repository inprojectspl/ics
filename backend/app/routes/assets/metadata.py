"""Document metadata endpoints (ADR-0015): `PATCH /{asset_id}/meta` and
`POST /{asset_id}/reviewed`.

Registered on `crud_router`. Editor or higher; read-only collaborators get
404 like every other write (anti-enumeration in `permissions`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions
from app.auth import CurrentUser
from app.db import get_session
from app.services import asset_metadata

from ._create_metadata import request_summary_source
from .crud import router


class AssetMetaIn(BaseModel):
    """Only the fields present in the body change; `null` clears a field."""

    model_config = ConfigDict(extra="forbid")

    summary: str | None = None
    doc_type: str | None = None
    maintainer_id: UUID | None = None
    review_due_at: datetime | None = None
    language: str | None = None
    properties: dict[str, Any] | None = None


@router.patch("/{asset_id}/meta")
async def patch_asset_meta(
    asset_id: UUID,
    body: AssetMetaIn,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> dict:
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    changed = await asset_metadata.update_metadata(
        session,
        asset,
        body.model_dump(exclude_unset=True),
        source=request_summary_source(request),
    )
    if changed:
        # Field names only: the summary text is content, not audit context.
        await audit.record_from_request(
            session,
            request,
            actor=user,
            action="asset_metadata_updated",
            target=f"asset:{asset.id}",
            payload={"fields": changed},
        )
        await session.commit()
    return await asset_metadata.metadata_detail(session, asset, user)


@router.post("/{asset_id}/reviewed")
async def mark_asset_reviewed(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    request: Request,
) -> dict:
    """Confirm the document is still current without changing its content."""
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    await asset_metadata.mark_reviewed(session, asset, user.id)
    await audit.record_from_request(
        session,
        request,
        actor=user,
        action="asset_reviewed",
        target=f"asset:{asset.id}",
        payload={"review_due_at": asset.review_due_at.isoformat() if asset.review_due_at else None},
    )
    await session.commit()
    return await asset_metadata.metadata_detail(session, asset, user)
