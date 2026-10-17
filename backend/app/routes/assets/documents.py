"""Document assets (PDF, Word/ODF): upload, and the raw PDF for the in-app
viewer (ADR-0013, ADR-0014). Office documents are shown as converted
Markdown, so only PDFs have a raw-bytes endpoint.
"""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import Depends, Query, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions, quota
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.html_bundle import content_type_for
from app.models import Asset, AssetVersion, Project, ShareLink, User
from app.routes._version_param import VersionParam, resolve_version_or_404
from app.routes.assets._create_metadata import CreateMetadataForm
from app.routes.assets._helpers import UploadShareMode
from app.routes.assets.crud import _upload_target_project
from app.routes.assets.crud import router as crud_router
from app.routes.assets.view import _gate_bundle_for_read_only
from app.routes.assets.view import router as view_router
from app.services import asset_security, documents, ocr, read_size, relation_extraction
from app.services.asset_metadata import CreateMetadata
from app.services.notifications import events as notification_events
from app.services.sharing import build_share_url
from app.services.upload import ByteBudget, chunked, one_chunk
from app.services.versions import entry_path_at_version
from app.slug import generate_slug, generate_token
from app.storage import storage_from_url


async def _read_capped(kind: str, file: UploadFile, settings: Settings) -> bytes:
    doc_type = documents.document_type(kind)
    budget = ByteBudget(
        doc_type.max_bytes(settings), "file too large", code=doc_type.too_large_code
    )
    return b"".join([chunk async for chunk in chunked(file, budget)])


async def _upload_document(
    kind: str,
    file: UploadFile,
    user: User,
    session: AsyncSession,
    settings: Settings,
    share_mode: str,
    project: Project | None,
    meta: CreateMetadata,
) -> dict:
    """Store one uploaded document as a new asset of `kind`. The file is
    converted before the asset row exists, so a broken or password-protected
    file never becomes an asset (its storage prefix is removed). A critical
    scan result skips the default share link, as for HTML bundles."""
    filename = documents.filename(kind, file.filename)
    data = await _read_capped(kind, file, settings)
    await quota.assert_can_grow(
        session, user.id, incoming_bytes=len(data), quota_bytes=user.storage_quota_bytes
    )

    slug = generate_slug()
    prefix = f"assets/{slug}"
    storage = storage_from_url(settings.storage_url)
    try:
        converted, _ = await asyncio.gather(
            documents.ingest(
                storage,
                kind=kind,
                storage_prefix=prefix,
                version=1,
                entry_path=filename,
                settings=settings,
                data=data,
            ),
            storage.put(f"{prefix}/v1/{filename}", one_chunk(data)),
        )
    except Exception:
        await storage.delete_prefix(prefix)
        raise

    asset = Asset(
        slug=slug,
        owner_id=user.id,
        content_updated_by=user.id,
        project_id=project.id if project else None,
        kind=kind,
        title=PurePosixPath(filename).stem or kind,
        storage_prefix=prefix,
        entry_path=filename,
        security_status="clean",
        size_bytes=len(data),
        version=1,
    )
    session.add(asset)
    meta.apply(asset)
    await session.flush()
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=1,
            storage_prefix=f"{prefix}/v1",
            size_bytes=len(data),
            created_by=user.id,
        )
    )
    scan = await asset_security.scan_and_apply(asset, settings, session, actor=user)
    share: ShareLink | None = None
    if not asset_security.publication_blocked(asset):
        share = ShareLink(
            asset_id=asset.id, token=generate_token(), mode=share_mode, created_by=user.id
        )
        session.add(share)
    asset.search_content = documents.search_content_of(kind, converted)
    await read_size.refresh_read_tokens(asset, settings, converted=converted)
    await relation_extraction.extract_from_content(
        session, asset, settings, user.id, converted=converted
    )
    ocr_run = ocr.queue_after_write(session, asset, 1, converted, settings, requested_by=user.id)
    summary = documents.summary_of(kind, converted)
    await audit.record(
        session,
        actor=user,
        action="asset_uploaded",
        target=f"asset:{asset.id}",
        payload={
            "kind": kind,
            "slug": slug,
            "size_bytes": len(data),
            **summary,
            "security": scan,
            "share_mode": share_mode if share else None,
        },
    )
    await session.commit()
    await notification_events.emit_created(asset, user)
    await ocr.enqueue(ocr_run, settings)
    # The conversion holds the meta fields, so the state needs no storage read.
    block = await ocr.ocr_block(session, asset, 1, settings, meta=converted)
    return {
        "id": str(asset.id),
        "slug": asset.slug,
        "title": asset.title,
        "kind": asset.kind,
        "share_url": build_share_url(settings, share.token) if share else None,
        "security_status": asset.security_status,
        **summary,
        "ocr": block,
    }


@crud_router.post("/pdf", status_code=status.HTTP_201_CREATED)
async def upload_pdf(
    file: UploadFile,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    meta: CreateMetadataForm,
    share_mode: Annotated[UploadShareMode, Query()] = "org_sso",
    project: Annotated[Project | None, Depends(_upload_target_project)] = None,
) -> dict:
    """Upload one PDF as a new `pdf_doc` asset (ADR-0013)."""
    return await _upload_document(
        "pdf_doc", file, user, session, settings, share_mode, project, meta
    )


@crud_router.post("/document", status_code=status.HTTP_201_CREATED)
async def upload_office_document(
    file: UploadFile,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    meta: CreateMetadataForm,
    share_mode: Annotated[UploadShareMode, Query()] = "org_sso",
    project: Annotated[Project | None, Depends(_upload_target_project)] = None,
) -> dict:
    """Upload one `.docx`, `.odt` or `.doc` as a new `office_doc` asset
    (ADR-0014). The format is decided by the content, not the extension."""
    return await _upload_document(
        "office_doc", file, user, session, settings, share_mode, project, meta
    )


async def pdf_response(asset: Asset, version: int, settings: Settings) -> StreamingResponse:
    """The stored PDF of one version, streamed, for the viewer. `attachment`
    plus a sandbox CSP: opened directly, the file downloads instead of
    running in the browser's PDF plugin on the app origin; the viewer
    fetches it."""
    entry = await entry_path_at_version(asset, version, settings)
    if entry is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "source_missing", "PDF file is missing")
    storage = storage_from_url(settings.storage_url)
    try:
        stream = await storage.get(f"{asset.storage_prefix}/v{version}/{entry}")
    except FileNotFoundError:
        raise ApiError(status.HTTP_404_NOT_FOUND, "source_missing", "PDF file is missing") from None
    return StreamingResponse(
        stream,
        media_type=content_type_for(entry),
        headers={
            "Content-Disposition": f'attachment; filename="{asset.slug}.pdf"',
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-Content-Type-Options": "nosniff",
            # Version bytes never change, but access can be revoked.
            "Cache-Control": "private, max-age=3600",
        },
    )


def assert_pdf(asset: Asset) -> None:
    if asset.kind != "pdf_doc":
        raise ApiError(status.HTTP_400_BAD_REQUEST, "pdf_only", "operation available only for PDFs")


@view_router.get("/by-slug/{slug}/pdf")
async def asset_pdf(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    version: VersionParam = None,
) -> Response:
    asset, role = await permissions.get_viewable_asset_by_slug(session, slug, user)
    assert_pdf(asset)
    _gate_bundle_for_read_only(role, asset)
    return await pdf_response(asset, resolve_version_or_404(asset, version), settings)


__all__ = ["assert_pdf", "asset_pdf", "pdf_response", "upload_office_document", "upload_pdf"]
