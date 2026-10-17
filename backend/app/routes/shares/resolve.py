"""Bearer share resolution for MCP clients: token (plus optional inline
password) to metadata and content in one call, since the browser flow is
cookie-based. The share mode is checked against the `CurrentUser` identity;
a user with a role on the asset skips it and does not consume `max_views`.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import audit, permissions
from app.auth import CurrentUser, require_mcp_rate_limit
from app.collections_io import (
    list_md_paths,
    list_version_files,
    normalize_collection_path,
    read_text,
    slice_lines,
)
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError
from app.services import documents, ocr
from app.services.ocr import OcrState
from app.util import ip_hash

from ._models import (
    ResolvedAssetOut,
    ResolvedShareOut,
    ShareResolveIn,
    ShareResolveOut,
)
from ._router import router
from ._shared import (
    _can_view_as_user,
    _increment_view_count,
    _resolve_share,
    _verify_share_password,
)


@router.post(
    "/api/share/{token}/resolve",
    dependencies=[Depends(require_mcp_rate_limit)],
)
async def share_resolve(
    token: str,
    body: ShareResolveIn,
    request: Request,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ShareResolveOut:
    share, asset = await _resolve_share(token, session)

    # A role on the asset skips the mode gate (they can read it anyway), but
    # lifecycle gates (410 in `_resolve_share`) apply to everyone.
    direct_role = await permissions.effective_role(session, user, asset)

    if direct_role is None:
        if share.mode == "password":
            if not body.password:
                raise ApiError(
                    status.HTTP_401_UNAUTHORIZED,
                    "share_password_required",
                    "this link is password protected; pass the password in the `password` field",
                )
            await _verify_share_password(share, body.password, request, session, actor=user)
        elif not _can_view_as_user(share, user, settings):
            code, detail = {
                "org_sso": (
                    "domain_not_allowed",
                    "the link requires an account in an allowed organisation domain",
                ),
                "magic_email": (
                    "email_not_allowed",
                    "your e-mail address is not on this link's recipient list",
                ),
            }.get(share.mode, ("share_access_denied", "access denied"))
            raise ApiError(status.HTTP_403_FORBIDDEN, code, detail)

    if asset.kind != "md_collection" and body.path is not None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            "collection_only",
            "`path` applies only to Markdown collections",
        )
    if asset.kind == "html_bundle" and body.lines is not None:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST, "markdown_only", "`lines` applies only to Markdown files"
        )

    content: str | None = None
    total_lines: int | None = None
    returned_range: list[int] | None = None
    tree: list[str] | None = None
    files: list[str] | None = None
    rel: str | None = None
    ocr_block: OcrState | None = None
    # Snapshot before the increment: the ORM UPDATE synchronizes the loaded
    # `share` object, so a later attribute read would already see the new
    # value and the +1 would be counted twice.
    view_count = share.view_count

    if asset.kind == "html_bundle":
        # Metadata only and no view counted, like `GET /doc`.
        files = await list_version_files(asset, asset.version, settings)
    else:
        rel = normalize_collection_path(body.path) if body.path else asset.entry_path
        if rel is None:
            raise ApiError(
                status.HTTP_404_NOT_FOUND, "entry_missing", "the asset has no entry file"
            )
        try:
            if asset.kind == "md_collection":
                raw, tree = await asyncio.gather(
                    read_text(asset, rel, settings),
                    list_md_paths(asset, settings),
                )
            elif documents.is_document(asset.kind):
                if direct_role is None:
                    # A guest does not get a document held for review, in
                    # any form (`/doc`, `/pdf`, `/download` refuse it too).
                    from app.routes.assets import assert_bundle_renderable_for_visitors

                    assert_bundle_renderable_for_visitors(asset)
                # Converted text, as from `file-mcp`, plus the OCR state.
                raw, ocr_block = await asyncio.gather(
                    documents.markdown(asset, asset.version, settings),
                    ocr.ocr_state(session, asset, asset.version, settings),
                )
            else:
                raw = await read_text(asset, rel, settings)
        except FileNotFoundError:
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                "file_not_found",
                f"file does not exist in the collection: {rel}",
            ) from None
        # Same paging as `file-mcp`: over the limit without `lines` is a 400.
        content, total_lines, returned_range = slice_lines(raw, body.lines)
        if direct_role is None:
            # Counts as a view like GET /doc; team reads don't.
            await _increment_view_count(session, share.id)
            view_count += 1

    # Snapshot before commit: expire_on_commit expires the attributes and
    # a read after commit would cost another SELECT round-trip.
    share_out = ResolvedShareOut(
        mode=share.mode,
        expires_at=share.expires_at,
        view_count=view_count,
        max_views=share.max_views,
    )
    asset_out = ResolvedAssetOut(
        id=str(asset.id),
        slug=asset.slug,
        title=asset.title,
        kind=asset.kind,
        version=asset.version,
        entry_path=asset.entry_path,
        size_bytes=asset.size_bytes,
        security_status=asset.security_status,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )

    await audit.record_from_request(
        session,
        request,
        actor=user,
        action="share_resolved",
        target=f"share:{share.id}",
        ip_hash=ip_hash(request),
    )
    await session.commit()

    return ShareResolveOut(
        share=share_out,
        asset=asset_out,
        path=rel,
        content=content,
        total_lines=total_lines,
        returned_range=returned_range,
        tree=tree,
        files=files,
        ocr=ocr_block,
    )
