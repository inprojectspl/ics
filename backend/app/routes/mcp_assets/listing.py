"""File inventory for MCP (`files-mcp`), with sizes from the storage listing."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app import permissions
from app.auth import CurrentUser
from app.collections_io import list_version_files_with_sizes
from app.config import get_settings
from app.db import get_session
from app.json_response import ORJSONResponse
from app.routes._version_param import VersionParam, resolve_version_or_404, version_echo
from app.services.versions import entry_from_paths

from ._content import ensure_mcp_file_kind
from ._router import router


@router.get("/by-slug/{slug}/files-mcp")
async def files_mcp(
    slug: str,
    user: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    version: VersionParam = None,
) -> ORJSONResponse:
    """File inventory; `entry_path` comes from the requested version's tree."""
    asset, _ = await permissions.get_asset_with_role(
        session, user=user, min_role="viewer", slug=slug
    )
    ensure_mcp_file_kind(asset, "files-mcp")
    settings = get_settings()
    v = resolve_version_or_404(asset, version)
    files = await list_version_files_with_sizes(asset, v, settings)
    # Entry is computed from the listing we already have; `entry_path_at_version`
    # would issue a second LIST on the same prefix (billed separately on S3).
    entry = entry_from_paths(asset, v, [p for p, _ in files])
    return ORJSONResponse(
        {
            "slug": asset.slug,
            "kind": asset.kind,
            **version_echo(asset, v),
            "entry_path": entry,
            "files": [{"path": p, "size_bytes": s} for p, s in files],
        }
    )
