"""OCR of scanned PDF pages (ADR-0021): the state of a version (viewer level)
and a run request for the current one (editor+)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.routes._version_param import VersionParam, resolve_version_or_404
from app.services import ocr
from app.services.ocr import secrets
from app.services.ocr.providers import get_provider

from .crud import router as crud_router
from .view import router as view_router


class OcrRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, max_length=32)
    # SecretStr keeps the key out of reprs and validation errors.
    api_key: SecretStr | None = Field(default=None, max_length=512)


@view_router.get("/by-slug/{slug}/ocr")
async def get_ocr(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    version: VersionParam = None,
) -> dict:
    """OCR state of the current version (or `?version=N`): the status, the
    engine, the dates and the page counts. Polled by the viewer while a run
    is queued or running."""
    asset, _ = await permissions.get_viewable_asset_by_slug(session, slug, user)
    v = resolve_version_or_404(asset, version)
    block = await ocr.ocr_block(session, asset, v, settings)
    if block is None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "ocr_not_supported", "OCR applies to PDF documents only"
        )
    return {"slug": asset.slug, "version": v, "ocr": block}


@crud_router.post("/{asset_id}/ocr", status_code=status.HTTP_202_ACCEPTED)
async def request_ocr(
    asset_id: UUID,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
    body: OcrRequestIn | None = None,
) -> dict:
    """Queue OCR of the current version (first run or retry); 409 while a run
    is active or when every page has text. A cloud engine's `api_key` is kept
    encrypted in Redis for this run only, never stored or logged."""
    body = body or OcrRequestIn()
    asset = await permissions.get_owned_asset_by_id(session, asset_id, user)
    api_key = (body.api_key.get_secret_value().strip() if body.api_key else "") or None
    row = await ocr.request_ocr(
        session,
        asset,
        settings,
        requested_by=user.id,
        provider=body.provider,
        api_key=api_key,
    )
    await audit.record_from_request(
        session,
        request,
        actor=user,
        action="asset_ocr_requested",
        target=f"asset:{asset.id}",
        payload={"version": asset.version, "provider": row.provider},
    )
    await session.commit()
    if api_key and get_provider(row.provider).needs_api_key:
        await secrets.store(asset.id, asset.version, api_key, settings)
    await ocr.enqueue(row, settings)
    state = ocr.ocr_view(row, settings)
    return {"slug": asset.slug, "version": asset.version, "ocr": state.model_dump(mode="json")}


__all__ = ["get_ocr", "request_ocr"]
