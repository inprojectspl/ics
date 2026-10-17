"""Shared `?version=N` contract for every read surface.

Imports no route package, so each of them can use it without import cycles.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Query, status

from app.config import Settings
from app.errors import ApiError
from app.models import Asset
from app.services.versions import (
    VersionNotFound,
    entry_path_at_version,
    resolve_preview_version,
)

VersionParam = Annotated[
    int | None,
    Query(ge=1, description="Read the given version, read-only (the current one when omitted)"),
]


def version_echo(asset: Asset, version: int) -> dict[str, int]:
    """Version fields of read responses: what was served and what is current."""
    return {"version": version, "current_version": asset.version}


def resolve_version_or_404(asset: Asset, version: int | None) -> int:
    """`resolve_preview_version` with `VersionNotFound` mapped to 404 (a
    missing version is a missing resource, like a missing slug)."""
    try:
        return resolve_preview_version(asset, version)
    except VersionNotFound as e:
        raise ApiError(status.HTTP_404_NOT_FOUND, "version_not_found", str(e)) from None


async def entry_path_or_404(asset: Asset, version: int, settings: Settings) -> str:
    """Entry file of the given version; 404 when the version has no files."""
    entry = await entry_path_at_version(asset, version, settings)
    if entry is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "version_empty", f"version v{version} has no files"
        )
    return entry
