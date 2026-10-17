"""Token-efficient endpoints for the MCP server (index, meta, outline, line
ranges, search snippets, tagging, undelete), mounted under `/api/assets`
alongside `routes.assets`."""

from __future__ import annotations

# Side-effect imports: each module adds its endpoints to `router`.
from . import (  # noqa: F401
    agent_view,
    index,
    lifecycle,
    listing,
    outline,
    partial_read,
    search,
    security,
    upload,
)
from ._router import router

__all__ = ["router"]
