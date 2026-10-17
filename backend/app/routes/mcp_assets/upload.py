"""JSON upload variant for html_bundle assets (programmatic alternative to multipart)."""

from __future__ import annotations

import asyncio
import base64
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions, quota
from app.auth import CurrentUser
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.jobs.queue import enqueue
from app.json_response import ORJSONResponse
from app.models import Asset, AssetVersion, ShareLink
from app.routes.assets._create_metadata import request_summary_source
from app.services import asset_metadata, read_size, relation_extraction
from app.services import asset_security as asset_security_svc
from app.services.notifications import events as notification_events
from app.services.upload import one_chunk
from app.slug import generate_slug, generate_token
from app.storage import storage_from_url

from ._models import HtmlBundleCreate
from ._router import router


@router.post("/html-json", status_code=201)
async def create_html_bundle_json(
    payload: HtmlBundleCreate,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    request: Request,
) -> ORJSONResponse:
    """JSON alternative to the multipart bundle upload, for MCP agents."""
    # Same gate as the multipart uploads, before any storage write.
    if payload.project_id is not None:
        await permissions.assert_project_contributor(session, user, payload.project_id)
    share_mode = payload.share_mode or "org_sso"
    meta = await asset_metadata.prepare_create_metadata(
        session,
        doc_type=payload.doc_type,
        summary=payload.summary,
        source=request_summary_source(request),
    )

    total = 0
    files_raw: list[tuple[str, bytes, str | None]] = []
    seen_paths: set[str] = set()
    for f in payload.files:
        if f.path in seen_paths:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST, "duplicate_path", f"duplicate path: {f.path}"
            )
        seen_paths.add(f.path)
        if f.content_text is not None and f.content_base64 is not None:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "invalid_file_content",
                f"{f.path}: only one of content_text/content_base64",
            )
        if f.content_text is not None:
            data = f.content_text.encode("utf-8")
        elif f.content_base64 is not None:
            try:
                data = base64.b64decode(f.content_base64, validate=True)
            except ValueError as e:
                raise ApiError(
                    status.HTTP_400_BAD_REQUEST, "invalid_file_content", f"{f.path}: invalid base64"
                ) from e
        else:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                "invalid_file_content",
                f"{f.path}: content_text or content_base64 required",
            )
        total += len(data)
        # Checked incrementally so we can reject before decoding the rest.
        quota.assert_bundle_fits(total_bytes=total, bundle_max_bytes=user.bundle_max_bytes)
        files_raw.append((f.path, data, f.mime))

    if payload.entry_path not in seen_paths:
        raise ApiError(status.HTTP_400_BAD_REQUEST, "invalid_entry_path", "entry_path not in files")

    storage = storage_from_url(settings.storage_url, settings)
    slug = generate_slug()
    prefix = f"assets/{slug}"

    sem = asyncio.Semaphore(8)

    async def _put_one(path: str, data: bytes) -> None:
        async with sem:
            # Same `{prefix}/v{N}/{path}` layout `serve_bundle_file` reads.
            await storage.put(f"{prefix}/v1/{path}", one_chunk(data))

    await asyncio.gather(*(_put_one(p, d) for p, d, _m in files_raw))

    asset = Asset(
        id=uuid4(),
        slug=slug,
        owner_id=user.id,
        content_updated_by=user.id,
        project_id=payload.project_id,
        kind="html_bundle",
        title=payload.title,
        storage_prefix=prefix,
        entry_path=payload.entry_path,
        size_bytes=total,
        tags=payload.tags,
        outline_status="stale",
    )
    session.add(asset)
    meta.apply(asset)
    session.add(
        AssetVersion(
            asset_id=asset.id,
            version=1,
            storage_prefix=f"{prefix}/v1",
            size_bytes=total,
            created_by=user.id,
        )
    )
    await asset_security_svc.scan_and_apply(asset, settings, session, actor=user)
    await read_size.refresh_read_tokens(asset, settings)
    await relation_extraction.extract_from_content(session, asset, settings, user.id)
    # A critical bundle gets no link until an admin approves it (as in multipart).
    blocked = asset_security_svc.publication_blocked(asset)
    if not blocked:
        session.add(
            ShareLink(
                asset_id=asset.id, token=generate_token(), mode=share_mode, created_by=user.id
            )
        )

    await audit.record_from_request(
        session,
        request,
        actor=user,
        action="asset_uploaded",
        target=f"asset:{asset.id}",
        payload={
            "kind": "html_bundle",
            "via": "json",
            "size": total,
            "share_mode": None if blocked else share_mode,
        },
    )
    await session.commit()
    await notification_events.emit_created(asset, user)
    await enqueue("rebuild_outline", str(asset.id), _job_id=f"outline:{asset.id}")
    return ORJSONResponse(
        {
            "id": str(asset.id),
            "slug": asset.slug,
            "title": asset.title,
            "kind": asset.kind,
            "entry_path": asset.entry_path,
            "file_count": len(files_raw),
            "size_bytes": total,
            "security_status": asset.security_status,
        },
        status_code=201,
    )
