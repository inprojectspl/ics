"""Generic asset routes refuse `micro_application` assets.

A micro-application changes only through plan/apply (migrations, release
switch, runtime state) and its package is readable only by publishers
through `/api/micro-applications/{id}/package`. Using an app grants no right
to its private sources, so every older read path (download, file, tree,
render, source, diff, versions, share links, MCP file/agent views, viewer
grants) and every older write path (content, files, versions, restore,
binding sync, uploads) answers with a stable code instead.
"""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import status

from app.constants import MICRO_APPLICATION
from app.errors import ApiError
from app.models import Asset

REQUIRES_AGENT_API = "microapp_requires_agent_api"
SOURCE_RESTRICTED = "microapp_source_restricted"
NOT_ADDRESSABLE = "microapp_not_addressable"
MANIFEST_NAME = "microapp.json"


def refuse_write(asset: Asset) -> None:
    if asset.kind == MICRO_APPLICATION:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            REQUIRES_AGENT_API,
            "micro-applications change only through plan/apply "
            "(ICS-MCP ics_microapp_plan / ics_microapp_apply)",
        )


def refuse_source(asset: Asset) -> None:
    if asset.kind == MICRO_APPLICATION:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            SOURCE_RESTRICTED,
            "a micro-application's package is not readable here; publishers use "
            f"/api/micro-applications/{asset.id}/package, users open the app itself",
        )


def refuse_addressing(asset: Asset) -> None:
    """A link may point at an app, never into it: its package files and
    headings are sources (listing them would show them), its content is
    data. Relations into an app carry no path or anchor, and its links are
    not extracted from anything."""
    if asset.kind == MICRO_APPLICATION:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            NOT_ADDRESSABLE,
            "a micro-application is linked as a whole: no file, anchor or extracted links",
        )


def refuse_manifest_upload(paths: Iterable[str]) -> None:
    """A plain upload that carries a micro-application manifest is refused
    instead of being stored as HTML or Markdown that looks like an app."""
    for p in paths:
        parts = p.strip("/").split("/")
        # At the root, or under the single folder a directory upload keeps.
        if parts[-1] == MANIFEST_NAME and len(parts) <= 2:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                REQUIRES_AGENT_API,
                "packages with microapp.json are created through ICS-MCP "
                "(ics_microapp_plan / ics_microapp_apply), not uploaded",
            )
