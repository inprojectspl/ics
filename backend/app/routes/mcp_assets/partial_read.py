"""Partial line-range read for md_single / md_collection / html_bundle assets;
pdf_doc and office_doc read as the Markdown of their converted text."""

from __future__ import annotations

import base64
from typing import Annotated

from fastapi import Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.collections_io import slice_lines
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.html_bundle import binary_file_detail, content_type_for
from app.json_response import ORJSONResponse
from app.models import Asset
from app.routes._version_param import VersionParam, resolve_version_or_404, version_echo
from app.services import documents
from app.services.asset_projection import freshness_block

from ._content import ensure_mcp_file_kind, load_agent_text, resolve_target_path
from ._router import router
from ._shared import _MAX_LINES_RANGE, _MCP_BASE64_MAX_BYTES

# Ceiling for `max_lines`; the byte cap in `slice_lines` stays the real guard.
_MAX_LINES_CEILING = 10_000


def _binary_payload(asset: Asset, target: str, raw: bytes, encoding: str | None) -> dict:
    """Non-UTF-8 bundle file: a structured 415, or the base64 payload when
    requested and small enough."""
    mime = content_type_for(target)
    if encoding != "base64":
        raise ApiError(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "binary_file",
            binary_file_detail(
                target, len(raw), "binary file; add encoding=base64 (limit 1 MB) or skip it"
            ),
        )
    if len(raw) > _MCP_BASE64_MAX_BYTES:
        raise ApiError(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "binary_too_large",
            f"binary file too large for base64 (size={len(raw)}, max={_MCP_BASE64_MAX_BYTES})",
        )
    return {
        "slug": asset.slug,
        "path": target,
        "content_base64": base64.b64encode(raw).decode("ascii"),
        "mime": mime,
        "size_bytes": len(raw),
        "encoding": "base64",
    }


@router.get("/by-slug/{slug}/file-mcp")
async def file_with_line_range(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    path: str | None = None,
    lines: Annotated[str | None, Query(pattern=r"^\d+-\d+$")] = None,
    encoding: Annotated[str | None, Query(pattern=r"^base64$")] = None,
    format: Annotated[str | None, Query(pattern=r"^(raw|markdown)$")] = None,
    max_lines: Annotated[int | None, Query(ge=1, le=_MAX_LINES_CEILING)] = None,
    version: VersionParam = None,
) -> ORJSONResponse:
    """`/by-slug/{slug}/file` with `lines=N-M` paging (2000 lines by default).

    `format=markdown` converts .html and drops Markdown comments before
    slicing; documents read as their converted Markdown. Bundle files are
    returned as source, never rendered, so the visitor `security_status`
    gate deliberately does not apply.
    """
    asset, role = await permissions.get_asset_with_role(
        session, user=user, min_role="viewer", slug=slug
    )
    if documents.is_document(asset.kind) and permissions.is_read_only(role):
        # A document held for review is withheld from read-only roles on
        # every content path (`/doc`, `/download`, `/pdf` too).
        from app.routes.assets import assert_bundle_renderable_for_visitors

        assert_bundle_renderable_for_visitors(asset)
    ensure_mcp_file_kind(asset, "file-mcp")
    settings = get_settings()
    v = resolve_version_or_404(asset, version)
    target = await resolve_target_path(asset, path, v, settings)
    loaded = await load_agent_text(
        asset,
        v,
        target,
        format=format,
        encoding=encoding,
        settings=settings,
        session=session,
    )
    # Freshness of the document (ADR-0015): a superseded one names its successor.
    block = await freshness_block(session, asset, user)
    signals = {
        "freshness": block["freshness"],
        "superseded_by": block["superseded_by"],
        "latest": block["latest"],
    }
    if loaded.text is None:
        return ORJSONResponse(
            {
                **_binary_payload(asset, target, loaded.blob, encoding),
                **version_echo(asset, v),
                **signals,
            }
        )

    content, total, returned_range = slice_lines(
        loaded.text, lines, max_lines=max_lines or _MAX_LINES_RANGE
    )

    return ORJSONResponse(
        {
            "slug": asset.slug,
            "path": target,
            "content": content,
            "total_lines": total,
            "returned_range": returned_range,
            **version_echo(asset, v),
            **loaded.extra,
            **signals,
        }
    )
